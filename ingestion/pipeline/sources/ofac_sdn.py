from __future__ import annotations

import asyncio
import csv
import re
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline.db_models import IngestionLog
from pipeline.exceptions import RecordParseError
from pipeline.models import IngestionResult
from pipeline.upsert import upsert_entities

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
    ("C.U.R.P.", re.compile(r"C\.U\.R\.P\.\s*" + _ID_SUFFIX)),
    ("R.F.C.", re.compile(r"R\.F\.C\.\s*" + _ID_SUFFIX)),
    ("USCC", re.compile(r"(?:Unified Social Credit Code \(USCC\)|USCC)\s*" + _ID_SUFFIX)),
    ("SWIFT/BIC", re.compile(r"(?:alt\. )?SWIFT/BIC\s*" + _ID_SUFFIX)),
    ("Trade License", re.compile(r"Trade License No\.\s*" + _ID_SUFFIX)),
    ("D.N.I.", re.compile(r"D\.N\.I\.\s*" + _ID_SUFFIX)),
    ("D-U-N-S", re.compile(r"D-U-N-S Number\s*" + _ID_SUFFIX)),
    ("Enterprise Number", re.compile(r"Enterprise Number\s*" + _ID_SUFFIX)),
    ("Driver's License", re.compile(r"Driver's License No\.\s*" + _ID_SUFFIX)),
    ("BIK", re.compile(r"(?:alt\. )?BIK\s*(?:\(RU\)\s*)?" + _ID_SUFFIX)),
    ("Phone Number", re.compile(r"Phone Number\s*" + _ID_SUFFIX)),
    ("License", re.compile(r"(?:alt\. )?License\s+" + _ID_SUFFIX)),
]

DIGITAL_CURRENCY_RE = re.compile(r"(?:alt\. )?Digital Currency Address - (\w+)\s+([^;]+?)(?:;|$)")

REGISTRATION_COUNTRY_RE = re.compile(r"Nationality of Registration ([^;]+)")

AKA_RE = re.compile(r"(a\.k\.a\.|f\.k\.a\.)\s+'([^']+)'")

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

    # Digital Currency Addresses have a different capture group layout:
    # group(1) = currency (e.g. "XBT"), group(2) = address
    for match in DIGITAL_CURRENCY_RE.finditer(remarks):
        currency = match.group(1).strip()
        address = match.group(2).strip()
        if address:
            identifiers.append(
                {
                    "id_type": f"Digital Currency Address - {currency}",
                    "id_value": address,
                    "country": None,
                }
            )

    return identifiers


def _parse_inline_aliases(remarks: str) -> list[dict[str, str | None]]:
    """Extract a.k.a./f.k.a. aliases from remarks text."""
    aliases: list[dict[str, str | None]] = []
    for match in AKA_RE.finditer(remarks):
        alias_type = "aka" if match.group(1) == "a.k.a." else "fka"
        aliases.append(
            {
                "alias_name": match.group(2).strip(),
                "alias_type": alias_type,
                "is_primary": False,
            }
        )
    return aliases


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

    vessels: list[dict[str, Any]] = []
    if entity_type == "vessel":
        vessels.append(
            {
                "vessel_name": sdn_row.get("sdn_name"),
                "imo_number": imo_match.group(1) if imo_match else None,
                "mmsi_number": mmsi_match.group(1) if mmsi_match else None,
                "vessel_type": sdn_row.get("vess_type"),
                "flag": sdn_row.get("vess_flag"),
                "tonnage": sdn_row.get("tonnage"),
                "build_year": int(build_year_match.group(1)) if build_year_match else None,
                "call_sign": sdn_row.get("call_sign"),
            }
        )

    # Extract country_of_registration from remarks for non-individual entities
    country_of_registration: str | None = None
    if entity_type == "entity" and remarks:
        reg_country_match = REGISTRATION_COUNTRY_RE.search(remarks)
        if reg_country_match:
            country_of_registration = reg_country_match.group(1).strip().rstrip(".")

    normalized_aliases = [
        {
            "alias_name": row.get("alt_name"),
            "alias_type": row.get("alt_type"),
            "is_primary": False,
        }
        for row in aliases
        if row.get("alt_name")
    ]

    # Merge inline a.k.a./f.k.a. aliases from remarks, deduplicating against alt.csv aliases
    if remarks:
        inline_aliases = _parse_inline_aliases(remarks)
        existing_names = {
            a["alias_name"].lower() for a in normalized_aliases if a.get("alias_name")
        }
        for ia in inline_aliases:
            if ia["alias_name"] and ia["alias_name"].lower() not in existing_names:
                normalized_aliases.append(ia)
                existing_names.add(ia["alias_name"].lower())

    normalized_addresses = [
        {
            "address": row.get("address"),
            "city": row.get("city_state"),
            "country": row.get("country"),
            "postal_code": None,
        }
        for row in addresses
        if any(row.get(f) for f in ("address", "city_state", "country"))
    ]

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
        "country_of_registration": country_of_registration,
        "remarks": remarks or None,
        "data_vintage": now,
        "last_updated": now,
        "raw_record": raw_record,
        "aliases": normalized_aliases,
        "addresses": normalized_addresses,
        "identifiers": identifiers,
        "vessels": vessels,
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
    records_removed = 0
    records_skipped = 0
    error_message: str | None = None
    status = "completed"

    try:
        sdn_rows = await asyncio.to_thread(_parse_csv, source_dir / "sdn.csv", SDN_COLUMNS)
        add_rows = await asyncio.to_thread(_parse_csv, source_dir / "add.csv", ADD_COLUMNS)
        alt_rows = await asyncio.to_thread(_parse_csv, source_dir / "alt.csv", ALT_COLUMNS)
        comments_rows = await asyncio.to_thread(
            _parse_csv, source_dir / "sdn_comments.csv", COMMENTS_COLUMNS
        )

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
            except RecordParseError:
                records_skipped += 1
                log.warning("record_parse_failed", source_id=ent_num, exc_info=True)

        log.info("records_parsed", total=len(parsed_entities), skipped=records_skipped)

        records_added, records_updated, records_removed = await upsert_entities(
            session, SOURCE_NAME, parsed_entities
        )

        if records_skipped > 0:
            status = "completed_with_errors"
            error_message = f"{records_skipped} record(s) skipped during parsing"

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
