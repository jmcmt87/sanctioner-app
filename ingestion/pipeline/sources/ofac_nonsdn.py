from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline.db_models import IngestionLog
from pipeline.exceptions import RecordParseError
from pipeline.models import IngestionResult
from pipeline.sources.ofac_sdn import (
    ADD_COLUMNS,
    ALT_COLUMNS,
    COMMENTS_COLUMNS,
    SDN_COLUMNS,
    _build_entity_dict,
    _parse_csv,
)
from pipeline.upsert import upsert_entities

logger = structlog.get_logger()

SOURCE_NAME = "ofac_nonsdn"


async def ingest_ofac_nonsdn(
    session: AsyncSession,
    data_dir: Path,
) -> IngestionResult:
    """Ingest OFAC Consolidated Non-SDN list. Reuses SDN parsing helpers."""
    started_at = datetime.now(UTC)
    now = started_at
    source_dir = data_dir / "ofac_nonsdn"

    log = logger.bind(source=SOURCE_NAME)
    log.info("ingestion_started", data_dir=str(source_dir))

    records_added = 0
    records_updated = 0
    records_removed = 0
    records_skipped = 0
    error_message: str | None = None
    status = "completed"

    try:
        sdn_rows = await asyncio.to_thread(_parse_csv, source_dir / "cons_prim.csv", SDN_COLUMNS)
        add_rows = await asyncio.to_thread(_parse_csv, source_dir / "cons_add.csv", ADD_COLUMNS)
        alt_rows = await asyncio.to_thread(_parse_csv, source_dir / "cons_alt.csv", ALT_COLUMNS)
        comments_rows = await asyncio.to_thread(
            _parse_csv, source_dir / "cons_comments.csv", COMMENTS_COLUMNS
        )

        log.info(
            "csv_files_parsed",
            prim_count=len(sdn_rows),
            add_count=len(add_rows),
            alt_count=len(alt_rows),
            comments_count=len(comments_rows),
        )

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
                    "skipping_invalid_record", source_id=ent_num, reason="missing primary_name"
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

    return IngestionResult(
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
