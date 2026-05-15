from __future__ import annotations

import csv
import re
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline.db_models import (
    EntityAddress,
    EntityAlias,
    EntityIdentifier,
    IngestionLog,
    SanctionedEntity,
    Vessel,
)
from pipeline.models import IngestionResult

logger = structlog.get_logger()

SOURCE_NAME = "ofac_sdn"
NULL_VALUE = "-0- "

SDN_COLUMNS = [
    "ent_num",
    "sdn_name",
    "sdn_type",
    "program",
    "title",
    "call_sign",
    "vess_type",
    "tonnage",
    "grt",
    "vess_flag",
    "vess_owner",
    "remarks",
]

ADD_COLUMNS = ["ent_num", "add_num", "address", "city_state", "country", "add_remarks"]

ALT_COLUMNS = ["ent_num", "alt_num", "alt_type", "alt_name", "alt_remarks"]

COMMENTS_COLUMNS = ["ent_num", "comments"]

DOB_FULL_RE = re.compile(r"DOB (\d{1,2} \w{3} \d{4})")
DOB_YEAR_RE = re.compile(r"DOB (\d{4})\b")
NATIONALITY_RE = re.compile(r"(?:^|;\s*)nationality ([^;]+)")
IMO_RE = re.compile(r"Vessel Registration Identification IMO (\d+)")
MMSI_RE = re.compile(r"MMSI (\d+)")
BUILD_YEAR_RE = re.compile(r"Vessel Year of Build (\d{4})")

_ID_SUFFIX = r"([^;(]+?)(?:\s*\(([^)]+)\))?(?:;|$)"
_PASSPORT_RE = re.compile(
    r"(?:alt\. )?Passport ([^;(]+?)"
    r"(?:\s*\(([^)]+)\))?"
    r"(?:\s*(?:issued|expires)[^;]*)?"
    r"(?:;|$)"
)

IDENTIFIER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Passport", _PASSPORT_RE),
    ("SSN", re.compile(r"SSN " + _ID_SUFFIX)),
    ("National ID", re.compile(r"National ID No\. " + _ID_SUFFIX)),
    ("Tax ID", re.compile(r"Tax ID No\. " + _ID_SUFFIX)),
    ("Cedula", re.compile(r"(?:alt\. )?Cedula No\. " + _ID_SUFFIX)),
    (
        "Registration Number",
        re.compile(
            r"Registration (?:Number|ID) " + _ID_SUFFIX,
        ),
    ),
    (
        "Legal Entity Number",
        re.compile(
            r"Legal Entity Number " + _ID_SUFFIX,
        ),
    ),
    ("Company Number", re.compile(r"Company Number " + _ID_SUFFIX)),
    (
        "Government Gazette Number",
        re.compile(
            r"Government Gazette Number " + _ID_SUFFIX,
        ),
    ),
    (
        "Business Registration Number",
        re.compile(
            r"Business Registration Number " + _ID_SUFFIX,
        ),
    ),
    (
        "Identification Number",
        re.compile(
            r"Identification Number " + _ID_SUFFIX,
        ),
    ),
]

MONTH_MAP = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _clean(value: str) -> str | None:
    """Return None for OFAC null sentinel, stripped string otherwise."""
    stripped = value.strip().strip('"')
    if stripped == NULL_VALUE.strip() or not stripped:
        return None
    return stripped


def _parse_csv(path: Path, columns: list[str]) -> list[dict[str, str | None]]:
    """Parse a headerless OFAC CSV file into a list of dicts."""
    rows: list[dict[str, str | None]] = []
    content = path.read_text(encoding="utf-8", errors="replace")
    reader = csv.reader(StringIO(content))
    for raw_row in reader:
        if not raw_row or not raw_row[0].strip():
            continue
        padded = raw_row + [None] * (len(columns) - len(raw_row))  # type: ignore[list-item]
        row = {}
        for i, col in enumerate(columns):
            val = padded[i]
            row[col] = _clean(val) if val is not None else None
        rows.append(row)
    return rows


def _parse_dob(remarks: str) -> date | None:
    """Extract first DOB from remarks. Returns None on failure."""
    match = DOB_FULL_RE.search(remarks)
    if match:
        try:
            parts = match.group(1).split()
            day = int(parts[0])
            month = MONTH_MAP.get(parts[1].lower()[:3])
            year = int(parts[2])
            if month:
                return date(year, month, day)
        except (ValueError, IndexError):
            pass
    match = DOB_YEAR_RE.search(remarks)
    if match:
        try:
            return date(int(match.group(1)), 1, 1)
        except ValueError:
            pass
    return None


def _parse_nationalities(remarks: str) -> list[str]:
    return [m.group(1).strip() for m in NATIONALITY_RE.finditer(remarks)]


def _parse_programs(program_str: str | None) -> list[str]:
    """Parse program field like 'IRAN] [SDGT] [IRGC' into a list."""
    if not program_str:
        return []
    parts = re.split(r"\]\s*\[", program_str)
    return [p.strip().strip("[]") for p in parts if p.strip().strip("[]")]


def _parse_identifiers(remarks: str) -> list[dict[str, str | None]]:
    """Extract typed identifiers from remarks text."""
    identifiers: list[dict[str, str | None]] = []
    for id_type, pattern in IDENTIFIER_PATTERNS:
        for match in pattern.finditer(remarks):
            id_value = match.group(1).strip()
            country = match.group(2).strip() if match.group(2) else None
            if id_value:
                identifiers.append({"id_type": id_type, "id_value": id_value, "country": country})
    return identifiers


def _normalize_entity_type(sdn_type: str | None) -> str:
    if not sdn_type:
        return "entity"
    lower = sdn_type.strip().lower()
    if lower == "individual":
        return "individual"
    if lower == "vessel":
        return "vessel"
    if lower == "aircraft":
        return "aircraft"
    return "entity"


def _build_entity_dict(
    sdn_row: dict[str, str | None],
    addresses: list[dict[str, str | None]],
    aliases: list[dict[str, str | None]],
    extended_remarks: str | None,
    now: datetime,
) -> dict[str, Any]:
    """Build a flat dict with all parsed fields for one SDN entity."""
    remarks = sdn_row.get("remarks") or ""
    if extended_remarks:
        remarks = remarks.rstrip(". ") + " " + extended_remarks if remarks else extended_remarks

    entity_type = _normalize_entity_type(sdn_row.get("sdn_type"))
    programs = _parse_programs(sdn_row.get("program"))

    dob = _parse_dob(remarks) if entity_type == "individual" and remarks else None
    nationalities = _parse_nationalities(remarks) if entity_type == "individual" and remarks else []
    identifiers = _parse_identifiers(remarks) if remarks else []

    imo_match = IMO_RE.search(remarks) if remarks else None
    mmsi_match = MMSI_RE.search(remarks) if remarks else None
    build_year_match = BUILD_YEAR_RE.search(remarks) if remarks else None

    vessel_data: dict[str, Any] | None = None
    if entity_type == "vessel":
        vessel_data = {
            "vessel_name": sdn_row.get("sdn_name"),
            "imo_number": imo_match.group(1) if imo_match else None,
            "mmsi_number": mmsi_match.group(1) if mmsi_match else None,
            "vessel_type": sdn_row.get("vess_type"),
            "flag": sdn_row.get("vess_flag"),
            "tonnage": sdn_row.get("tonnage"),
            "build_year": int(build_year_match.group(1)) if build_year_match else None,
            "call_sign": sdn_row.get("call_sign"),
        }

    raw_record: dict[str, Any] = {
        "sdn_row": {k: v for k, v in sdn_row.items()},
        "addresses": addresses,
        "aliases": aliases,
    }
    if extended_remarks:
        raw_record["extended_remarks"] = extended_remarks

    return {
        "source_id": sdn_row["ent_num"],
        "entity_type": entity_type,
        "primary_name": sdn_row["sdn_name"],
        "programs": programs or None,
        "date_of_birth": dob,
        "nationality": nationalities or None,
        "remarks": remarks or None,
        "data_vintage": now,
        "last_updated": now,
        "raw_record": raw_record,
        "vessel_data": vessel_data,
        "identifiers": identifiers,
        "parsed_addresses": addresses,
        "parsed_aliases": aliases,
    }


async def ingest_ofac_sdn(
    session: AsyncSession,
    data_dir: Path,
) -> IngestionResult:
    """Ingest OFAC SDN list from local CSV files into the database."""
    started_at = datetime.now(UTC)
    now = started_at
    source_dir = data_dir / "ofac_sdn"

    log = logger.bind(source=SOURCE_NAME)
    log.info("ingestion_started", data_dir=str(source_dir))

    records_added = 0
    records_updated = 0
    records_skipped = 0
    error_message: str | None = None
    status = "completed"

    try:
        sdn_rows = _parse_csv(source_dir / "sdn.csv", SDN_COLUMNS)
        add_rows = _parse_csv(source_dir / "add.csv", ADD_COLUMNS)
        alt_rows = _parse_csv(source_dir / "alt.csv", ALT_COLUMNS)
        comments_rows = _parse_csv(source_dir / "sdn_comments.csv", COMMENTS_COLUMNS)

        log.info(
            "csv_files_parsed",
            sdn_count=len(sdn_rows),
            add_count=len(add_rows),
            alt_count=len(alt_rows),
            comments_count=len(comments_rows),
        )

        # Index addresses, aliases, and comments by ent_num
        addresses_by_ent: dict[str, list[dict[str, str | None]]] = {}
        for row in add_rows:
            ent = row["ent_num"]
            if ent:
                addresses_by_ent.setdefault(ent, []).append(row)

        aliases_by_ent: dict[str, list[dict[str, str | None]]] = {}
        for row in alt_rows:
            ent = row["ent_num"]
            if ent:
                aliases_by_ent.setdefault(ent, []).append(row)

        comments_by_ent: dict[str, str] = {}
        for row in comments_rows:
            ent = row["ent_num"]
            if ent and row.get("comments"):
                existing = comments_by_ent.get(ent, "")
                comment = row["comments"]
                comments_by_ent[ent] = (existing + " " + comment).strip() if existing else comment

        # Build parsed entities
        parsed_entities: list[dict[str, Any]] = []
        for sdn_row in sdn_rows:
            ent_num = sdn_row.get("ent_num")
            if not ent_num:
                records_skipped += 1
                log.warning("skipping_invalid_record", reason="missing ent_num")
                continue

            name = sdn_row.get("sdn_name")
            if not name:
                records_skipped += 1
                log.warning(
                    "skipping_invalid_record",
                    source_id=ent_num,
                    reason="missing primary_name",
                )
                continue

            try:
                entity_dict = _build_entity_dict(
                    sdn_row,
                    addresses=addresses_by_ent.get(ent_num, []),
                    aliases=aliases_by_ent.get(ent_num, []),
                    extended_remarks=comments_by_ent.get(ent_num),
                    now=now,
                )
                parsed_entities.append(entity_dict)
            except Exception:
                records_skipped += 1
                log.warning("record_parse_failed", source_id=ent_num, exc_info=True)

        log.info("records_parsed", total=len(parsed_entities), skipped=records_skipped)

        # Upsert entities in batches
        existing_ids: set[str] = set()
        result = await session.execute(
            select(SanctionedEntity.source_id).where(SanctionedEntity.source == SOURCE_NAME)
        )
        existing_ids = {row[0] for row in result}

        incoming_ids: set[str] = set()

        batch_size = 500
        for batch_start in range(0, len(parsed_entities), batch_size):
            batch = parsed_entities[batch_start : batch_start + batch_size]

            for entity_dict in batch:
                source_id = entity_dict["source_id"]
                incoming_ids.add(source_id)
                is_update = source_id in existing_ids

                stmt = insert(SanctionedEntity).values(
                    source=SOURCE_NAME,
                    source_id=source_id,
                    entity_type=entity_dict["entity_type"],
                    primary_name=entity_dict["primary_name"],
                    programs=entity_dict["programs"],
                    date_of_birth=entity_dict["date_of_birth"],
                    nationality=entity_dict["nationality"],
                    remarks=entity_dict["remarks"],
                    data_vintage=entity_dict["data_vintage"],
                    last_updated=entity_dict["last_updated"],
                    raw_record=entity_dict["raw_record"],
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["source", "source_id"],
                    set_={
                        "entity_type": stmt.excluded.entity_type,
                        "primary_name": stmt.excluded.primary_name,
                        "programs": stmt.excluded.programs,
                        "date_of_birth": stmt.excluded.date_of_birth,
                        "nationality": stmt.excluded.nationality,
                        "remarks": stmt.excluded.remarks,
                        "data_vintage": stmt.excluded.data_vintage,
                        "last_updated": stmt.excluded.last_updated,
                        "raw_record": stmt.excluded.raw_record,
                    },
                )
                result = await session.execute(stmt)

                if is_update:
                    records_updated += 1
                else:
                    records_added += 1

                # Get the entity id for child inserts
                ent_result = await session.execute(
                    select(SanctionedEntity.id).where(
                        SanctionedEntity.source == SOURCE_NAME,
                        SanctionedEntity.source_id == source_id,
                    )
                )
                entity_id = ent_result.scalar_one()

                # Delete existing children and re-insert
                await session.execute(delete(EntityAlias).where(EntityAlias.entity_id == entity_id))
                await session.execute(
                    delete(EntityAddress).where(EntityAddress.entity_id == entity_id)
                )
                await session.execute(
                    delete(EntityIdentifier).where(EntityIdentifier.entity_id == entity_id)
                )
                await session.execute(delete(Vessel).where(Vessel.entity_id == entity_id))

                # Insert aliases
                for alias_row in entity_dict["parsed_aliases"]:
                    alias_name = alias_row.get("alt_name")
                    if alias_name:
                        session.add(
                            EntityAlias(
                                entity_id=entity_id,
                                alias_name=alias_name,
                                alias_type=alias_row.get("alt_type"),
                                is_primary=False,
                            )
                        )

                # Insert addresses
                for addr_row in entity_dict["parsed_addresses"]:
                    if any(addr_row.get(f) for f in ("address", "city_state", "country")):
                        session.add(
                            EntityAddress(
                                entity_id=entity_id,
                                address=addr_row.get("address"),
                                city=addr_row.get("city_state"),
                                country=addr_row.get("country"),
                            )
                        )

                # Insert identifiers
                for ident in entity_dict["identifiers"]:
                    session.add(
                        EntityIdentifier(
                            entity_id=entity_id,
                            id_type=ident["id_type"],
                            id_value=ident["id_value"],
                            country=ident.get("country"),
                        )
                    )

                # Insert vessel data
                if entity_dict["vessel_data"]:
                    vd = entity_dict["vessel_data"]
                    session.add(
                        Vessel(
                            entity_id=entity_id,
                            vessel_name=vd["vessel_name"],
                            imo_number=vd["imo_number"],
                            mmsi_number=vd["mmsi_number"],
                            vessel_type=vd["vessel_type"],
                            flag=vd["flag"],
                            tonnage=vd["tonnage"],
                            build_year=vd["build_year"],
                            call_sign=vd["call_sign"],
                        )
                    )

            await session.flush()

        # Detect removed entities
        removed_ids = existing_ids - incoming_ids
        records_removed = len(removed_ids)
        if removed_ids:
            await session.execute(
                delete(SanctionedEntity).where(
                    SanctionedEntity.source == SOURCE_NAME,
                    SanctionedEntity.source_id.in_(removed_ids),
                )
            )
            log.info("records_removed", count=records_removed)

        if records_skipped > 0:
            status = "completed_with_errors"

    except Exception as e:
        status = "failed"
        error_message = str(e)
        log.exception("ingestion_failed", error=error_message)
        raise
    finally:
        completed_at = datetime.now(UTC)

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
