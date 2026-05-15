"""EU Consolidated Financial Sanctions List ingestion parser.

Parses the EU sanctions XML file (namespace: http://eu.europa.ec/fpi/fsd/export)
and upserts sanctioned entities into the database following the six-step
ingestion pattern.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import structlog
from lxml import etree
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline.db_models import IngestionLog
from pipeline.models import IngestionResult
from pipeline.upsert import upsert_entities

logger = structlog.get_logger()

SOURCE_NAME = "eu_consolidated"
NS = {"ns": "http://eu.europa.ec/fpi/fsd/export"}

# Regex to extract regulation number from numberTitle like "269/2014 (OJ L78)"
REGULATION_NUMBER_RE = re.compile(r"(\d+/\d{4})")


def _attr(element: etree._Element, name: str) -> str | None:
    """Get an attribute value, returning None for empty strings."""
    val = element.get(name, "")
    return val.strip() if val and val.strip() else None


def _parse_xml(xml_path: Path) -> tuple[list[etree._Element], datetime | None]:
    """Parse the EU sanctions XML file and return entity elements + generation date.

    Returns:
        Tuple of (list of sanctionEntity elements, generation date from root).
    """
    tree = etree.parse(xml_path)  # noqa: S320 -- trusted local file from known EU source
    root = tree.getroot()

    # Extract generation date from root element
    generation_date_str = root.get("generationDate")
    generation_date: datetime | None = None
    if generation_date_str:
        try:
            generation_date = datetime.fromisoformat(generation_date_str)
        except ValueError:
            logger.warning(
                "invalid_generation_date",
                value=generation_date_str,
            )

    entities = root.findall(".//ns:sanctionEntity", NS)
    return entities, generation_date


def _normalize_entity_type(subject_type_code: str | None) -> str:
    """Map EU subjectType code to our normalized entity_type."""
    if not subject_type_code:
        return "entity"
    code = subject_type_code.strip().lower()
    if code == "person":
        return "individual"
    return "entity"


def _parse_date(date_str: str | None) -> date | None:
    """Parse a date string in YYYY-MM-DD format."""
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None


def _extract_primary_name(
    name_aliases: list[etree._Element],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Extract the primary name and build alias records from nameAlias elements.

    Primary name selection strategy:
    1. First English nameAlias with strong="true" that has a wholeName
    2. First nameAlias with strong="true" that has a wholeName (any language)
    3. First nameAlias with a wholeName

    Returns:
        Tuple of (primary_name, list of alias dicts for non-primary names).
    """
    primary_name: str | None = None
    primary_logical_id: str | None = None
    all_aliases: list[dict[str, Any]] = []

    # Collect all name alias data
    for na in name_aliases:
        whole_name = _attr(na, "wholeName")
        if not whole_name:
            continue

        first_name = _attr(na, "firstName") or ""
        middle_name = _attr(na, "middleName") or ""
        last_name = _attr(na, "lastName") or ""
        language = _attr(na, "nameLanguage") or ""
        strong = na.get("strong", "").lower() == "true"
        logical_id = _attr(na, "logicalId")

        alias_info = {
            "whole_name": whole_name,
            "first_name": first_name,
            "middle_name": middle_name,
            "last_name": last_name,
            "language": language,
            "strong": strong,
            "logical_id": logical_id,
            "function": _attr(na, "function"),
            "gender": _attr(na, "gender"),
            "title": _attr(na, "title"),
        }
        all_aliases.append(alias_info)

    # Select primary name: prefer English strong name, then any strong name, then first available
    for alias in all_aliases:
        if alias["strong"] and alias["language"].upper() == "EN":
            primary_name = alias["whole_name"]
            primary_logical_id = alias["logical_id"]
            break

    if not primary_name:
        for alias in all_aliases:
            if alias["strong"]:
                primary_name = alias["whole_name"]
                primary_logical_id = alias["logical_id"]
                break

    if not primary_name and all_aliases:
        primary_name = all_aliases[0]["whole_name"]
        primary_logical_id = all_aliases[0]["logical_id"]

    # Build non-primary alias records
    non_primary_aliases = [a for a in all_aliases if a["logical_id"] != primary_logical_id]

    return primary_name, non_primary_aliases


def _extract_citizenships(entity_el: etree._Element) -> list[str]:
    """Extract nationality/citizenship country descriptions."""
    citizenships: list[str] = []
    for cit in entity_el.findall("ns:citizenship", NS):
        country = _attr(cit, "countryDescription")
        if country and country not in citizenships:
            citizenships.append(country)
    return citizenships


def _extract_birthdate(entity_el: etree._Element) -> date | None:
    """Extract the first complete birthdate from birthdate elements."""
    for bd in entity_el.findall("ns:birthdate", NS):
        # Try the full birthdate attribute first
        bd_str = _attr(bd, "birthdate")
        if bd_str:
            parsed = _parse_date(bd_str)
            if parsed:
                return parsed

        # Fall back to individual components
        year_str = _attr(bd, "year")
        month_str = _attr(bd, "monthOfYear")
        day_str = _attr(bd, "dayOfMonth")
        if year_str:
            try:
                year = int(year_str)
                month = int(month_str) if month_str else 1
                day = int(day_str) if day_str else 1
                return date(year, month, day)
            except (ValueError, TypeError):
                continue
    return None


def _extract_addresses(entity_el: etree._Element) -> list[dict[str, str | None]]:
    """Extract address records from address elements."""
    addresses: list[dict[str, str | None]] = []
    for addr in entity_el.findall("ns:address", NS):
        street = _attr(addr, "street")
        city = _attr(addr, "city")
        country = _attr(addr, "countryDescription")
        postal_code = _attr(addr, "zipCode")
        region = _attr(addr, "region")

        if any([street, city, country]):
            # Combine street and region for the address field
            address_parts = [p for p in [street, region] if p]
            addresses.append(
                {
                    "address": ", ".join(address_parts) if address_parts else None,
                    "city": city,
                    "country": country,
                    "postal_code": postal_code,
                }
            )
    return addresses


def _extract_identifications(entity_el: etree._Element) -> list[dict[str, str | None]]:
    """Extract identification records (passports, IDs, etc.)."""
    identifiers: list[dict[str, str | None]] = []
    for ident in entity_el.findall("ns:identification", NS):
        number = _attr(ident, "number")
        id_type_desc = _attr(ident, "identificationTypeDescription")
        id_type_code = _attr(ident, "identificationTypeCode")
        country = _attr(ident, "countryDescription")

        if number:
            identifiers.append(
                {
                    "id_type": id_type_desc or id_type_code or "Unknown",
                    "id_value": number,
                    "country": country,
                }
            )
    return identifiers


def _extract_regulations(
    entity_el: etree._Element,
) -> tuple[list[str], list[str], date | None]:
    """Extract legal_basis, programmes, and earliest regulation publication date.

    Returns:
        Tuple of (legal_basis list, programmes list, earliest_publication_date).
    """
    legal_basis_set: set[str] = set()
    programmes_set: set[str] = set()
    earliest_date: date | None = None

    for reg in entity_el.findall("ns:regulation", NS):
        number_title = _attr(reg, "numberTitle")
        programme = _attr(reg, "programme")
        pub_date_str = _attr(reg, "publicationDate")

        if number_title:
            # Extract regulation number like "269/2014" from "269/2014 (OJ L78)"
            match = REGULATION_NUMBER_RE.search(number_title)
            if match:
                legal_basis_set.add(f"Reg. {match.group(1)}")

        if programme:
            programmes_set.add(programme)

        if pub_date_str:
            pub_date = _parse_date(pub_date_str)
            if pub_date and (earliest_date is None or pub_date < earliest_date):
                earliest_date = pub_date

    return sorted(legal_basis_set), sorted(programmes_set), earliest_date


def _extract_remarks(entity_el: etree._Element) -> str | None:
    """Extract and concatenate all remark texts."""
    remarks_parts: list[str] = []
    for remark in entity_el.findall("ns:remark", NS):
        if remark.text and remark.text.strip():
            remarks_parts.append(remark.text.strip())
    return "; ".join(remarks_parts) if remarks_parts else None


def _build_raw_record(
    entity_el: etree._Element,
    name_aliases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the raw_record JSONB dict preserving all original data."""
    raw: dict[str, Any] = {
        "eu_reference_number": _attr(entity_el, "euReferenceNumber"),
        "logical_id": _attr(entity_el, "logicalId"),
        "united_nation_id": _attr(entity_el, "unitedNationId"),
        "designation_date": _attr(entity_el, "designationDate"),
        "designation_details": _attr(entity_el, "designationDetails"),
    }

    # Subject type
    subj = entity_el.find("ns:subjectType", NS)
    if subj is not None:
        raw["subject_type"] = {
            "code": _attr(subj, "code"),
            "classification_code": _attr(subj, "classificationCode"),
        }

    # All name aliases (with language info for audit)
    raw["name_aliases"] = [
        {
            "whole_name": a["whole_name"],
            "first_name": a["first_name"],
            "last_name": a["last_name"],
            "language": a["language"],
            "strong": a["strong"],
            "function": a["function"],
            "title": a["title"],
        }
        for a in name_aliases
    ]

    # Citizenships
    citizenships = []
    for cit in entity_el.findall("ns:citizenship", NS):
        citizenships.append(
            {
                "country_iso2": _attr(cit, "countryIso2Code"),
                "country_description": _attr(cit, "countryDescription"),
            }
        )
    if citizenships:
        raw["citizenships"] = citizenships

    # Birthdates
    birthdates = []
    for bd in entity_el.findall("ns:birthdate", NS):
        birthdates.append(
            {
                "birthdate": _attr(bd, "birthdate"),
                "year": _attr(bd, "year"),
                "month": _attr(bd, "monthOfYear"),
                "day": _attr(bd, "dayOfMonth"),
                "city": _attr(bd, "city"),
                "country_iso2": _attr(bd, "countryIso2Code"),
                "country_description": _attr(bd, "countryDescription"),
            }
        )
    if birthdates:
        raw["birthdates"] = birthdates

    # Addresses
    addresses = []
    for addr in entity_el.findall("ns:address", NS):
        addresses.append(
            {
                "street": _attr(addr, "street"),
                "city": _attr(addr, "city"),
                "zip_code": _attr(addr, "zipCode"),
                "region": _attr(addr, "region"),
                "country_iso2": _attr(addr, "countryIso2Code"),
                "country_description": _attr(addr, "countryDescription"),
            }
        )
    if addresses:
        raw["addresses"] = addresses

    # Identifications
    identifications = []
    for ident in entity_el.findall("ns:identification", NS):
        identifications.append(
            {
                "number": _attr(ident, "number"),
                "type_code": _attr(ident, "identificationTypeCode"),
                "type_description": _attr(ident, "identificationTypeDescription"),
                "country_iso2": _attr(ident, "countryIso2Code"),
                "country_description": _attr(ident, "countryDescription"),
                "diplomatic": _attr(ident, "diplomatic"),
            }
        )
    if identifications:
        raw["identifications"] = identifications

    # Regulations
    regulations = []
    for reg in entity_el.findall("ns:regulation", NS):
        regulations.append(
            {
                "regulation_type": _attr(reg, "regulationType"),
                "organisation_type": _attr(reg, "organisationType"),
                "publication_date": _attr(reg, "publicationDate"),
                "entry_into_force_date": _attr(reg, "entryIntoForceDate"),
                "number_title": _attr(reg, "numberTitle"),
                "programme": _attr(reg, "programme"),
            }
        )
    if regulations:
        raw["regulations"] = regulations

    # Remarks
    remarks = []
    for rem in entity_el.findall("ns:remark", NS):
        if rem.text and rem.text.strip():
            remarks.append(rem.text.strip())
    if remarks:
        raw["remarks"] = remarks

    return raw


def _build_entity_dict(
    entity_el: etree._Element,
    now: datetime,
) -> dict[str, Any]:
    """Parse a single sanctionEntity XML element into a flat dict with all fields."""
    eu_ref = _attr(entity_el, "euReferenceNumber")
    if not eu_ref:
        msg = "Missing euReferenceNumber"
        raise ValueError(msg)

    # Subject type
    subj = entity_el.find("ns:subjectType", NS)
    subject_code = _attr(subj, "code") if subj is not None else None
    entity_type = _normalize_entity_type(subject_code)

    # Names
    name_alias_elements = entity_el.findall("ns:nameAlias", NS)
    primary_name, other_aliases = _extract_primary_name(name_alias_elements)
    if not primary_name:
        msg = f"No name found for entity {eu_ref}"
        raise ValueError(msg)

    # Citizenships / nationality
    citizenships = _extract_citizenships(entity_el) if entity_type == "individual" else []

    # Birthdate
    dob = _extract_birthdate(entity_el) if entity_type == "individual" else None

    # Addresses
    addresses = _extract_addresses(entity_el)

    # Identifications
    identifiers = _extract_identifications(entity_el)

    # Regulations -> legal_basis, programmes
    legal_basis, programmes, _earliest_reg_date = _extract_regulations(entity_el)

    # Remarks
    remarks = _extract_remarks(entity_el)

    # Designation date (list_date)
    designation_date = _parse_date(_attr(entity_el, "designationDate"))

    # Build raw record for audit
    # We need all aliases including primary for the raw record
    all_alias_info = other_aliases.copy()
    # Add primary name back into alias info for raw record
    primary_alias = {
        "whole_name": primary_name,
        "first_name": "",
        "last_name": "",
        "language": "",
        "strong": True,
        "function": None,
        "title": None,
    }
    all_alias_info.insert(0, primary_alias)

    raw_record = _build_raw_record(entity_el, all_alias_info)

    normalized_aliases = [
        {
            "alias_name": a["whole_name"],
            "alias_type": f"aka ({a['language']})" if a.get("language") else "aka",
            "is_primary": False,
        }
        for a in other_aliases
        if a.get("whole_name")
    ]

    return {
        "source_id": eu_ref,
        "entity_type": entity_type,
        "primary_name": primary_name,
        "programs": programmes or None,
        "legal_basis": legal_basis or None,
        "date_of_birth": dob,
        "nationality": citizenships or None,
        "remarks": remarks,
        "list_date": designation_date,
        "data_vintage": now,
        "last_updated": now,
        "raw_record": raw_record,
        "aliases": normalized_aliases,
        "addresses": addresses,
        "identifiers": identifiers,
        "vessels": [],
    }


async def ingest_eu_sanctions(
    session: AsyncSession,
    data_dir: Path,
) -> IngestionResult:
    """Ingest EU Consolidated Financial Sanctions List from XML into the database."""
    started_at = datetime.now(UTC)
    now = started_at
    source_dir = data_dir / "eu_consolidated"
    xml_path = source_dir / "eu_sanctions_list.xml"

    log = logger.bind(source=SOURCE_NAME)
    log.info("ingestion_started", data_dir=str(source_dir))

    records_added = 0
    records_updated = 0
    records_removed = 0
    records_skipped = 0
    error_message: str | None = None
    status = "completed"

    try:
        # Step 1 + 2: Parse the XML
        entity_elements, generation_date = _parse_xml(xml_path)
        if generation_date:
            now = generation_date

        log.info("xml_parsed", entity_count=len(entity_elements))

        # Step 3 + 4: Validate, map to dicts
        parsed_entities: list[dict[str, Any]] = []
        for entity_el in entity_elements:
            eu_ref = _attr(entity_el, "euReferenceNumber") or "unknown"
            try:
                entity_dict = _build_entity_dict(entity_el, now)
                parsed_entities.append(entity_dict)
            except (ValueError, TypeError) as e:
                records_skipped += 1
                log.warning(
                    "record_parse_failed",
                    source_id=eu_ref,
                    reason=str(e),
                )

        log.info("records_parsed", total=len(parsed_entities), skipped=records_skipped)

        records_added, records_updated, records_removed = await upsert_entities(
            session, SOURCE_NAME, parsed_entities
        )

        if records_skipped > 0:
            status = "completed_with_errors"

    except Exception as e:
        status = "failed"
        error_message = str(e)
        log.exception("ingestion_failed", error=error_message)
        raise
    finally:
        completed_at = datetime.now(UTC)

        # Step 6: Log to ingestion_log
        session.add(
            IngestionLog(
                source=SOURCE_NAME,
                ingestion_type="full",
                started_at=started_at,
                completed_at=completed_at,
                records_processed=records_added + records_updated + records_skipped,
                records_added=records_added,
                records_updated=records_updated,
                records_removed=records_removed if status != "failed" else 0,
                status=status,
                error_message=error_message,
                source_vintage=now,
            )
        )
        await session.commit()

    ingestion_result = IngestionResult(
        source=SOURCE_NAME,
        ingestion_type="full",
        started_at=started_at,
        completed_at=completed_at,
        records_processed=records_added + records_updated + records_skipped,
        records_added=records_added,
        records_updated=records_updated,
        records_removed=records_removed,
        records_skipped=records_skipped,
        status=status,
        error_message=error_message,
        source_vintage=now,
    )

    log.info(
        "ingestion_completed",
        status=status,
        records_processed=ingestion_result.records_processed,
        records_added=records_added,
        records_updated=records_updated,
        records_removed=records_removed,
        records_skipped=records_skipped,
        duration_seconds=(completed_at - started_at).total_seconds(),
    )

    return ingestion_result
