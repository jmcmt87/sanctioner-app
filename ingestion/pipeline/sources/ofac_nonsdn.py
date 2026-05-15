from __future__ import annotations

from datetime import UTC, datetime
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
from pipeline.sources.ofac_sdn import (
    ADD_COLUMNS,
    ALT_COLUMNS,
    COMMENTS_COLUMNS,
    SDN_COLUMNS,
    _build_entity_dict,
    _parse_csv,
)

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
        sdn_rows = _parse_csv(source_dir / "cons_prim.csv", SDN_COLUMNS)
        add_rows = _parse_csv(source_dir / "cons_add.csv", ADD_COLUMNS)
        alt_rows = _parse_csv(source_dir / "cons_alt.csv", ALT_COLUMNS)
        comments_rows = _parse_csv(source_dir / "cons_comments.csv", COMMENTS_COLUMNS)

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
            except Exception:
                records_skipped += 1
                log.warning("record_parse_failed", source_id=ent_num, exc_info=True)

        log.info("records_parsed", total=len(parsed_entities), skipped=records_skipped)

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
                await session.execute(stmt)

                if is_update:
                    records_updated += 1
                else:
                    records_added += 1

                ent_result = await session.execute(
                    select(SanctionedEntity.id).where(
                        SanctionedEntity.source == SOURCE_NAME,
                        SanctionedEntity.source_id == source_id,
                    )
                )
                entity_id = ent_result.scalar_one()

                await session.execute(delete(EntityAlias).where(EntityAlias.entity_id == entity_id))
                await session.execute(
                    delete(EntityAddress).where(EntityAddress.entity_id == entity_id)
                )
                await session.execute(
                    delete(EntityIdentifier).where(EntityIdentifier.entity_id == entity_id)
                )
                await session.execute(delete(Vessel).where(Vessel.entity_id == entity_id))

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

                for ident in entity_dict["identifiers"]:
                    session.add(
                        EntityIdentifier(
                            entity_id=entity_id,
                            id_type=ident["id_type"],
                            id_value=ident["id_value"],
                            country=ident.get("country"),
                        )
                    )

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
