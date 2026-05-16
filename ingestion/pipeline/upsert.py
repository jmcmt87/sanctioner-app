from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline.db_models import (
    EntityAddress,
    EntityAlias,
    EntityIdentifier,
    EntityRelationship,
    SanctionedEntity,
    Vessel,
)

logger = structlog.get_logger()


async def upsert_entities(
    session: AsyncSession,
    source_name: str,
    entities: list[dict[str, Any]],
    batch_size: int = 500,
) -> tuple[int, int, int]:
    """Upsert parsed entities and their child records into the database.

    Each entity dict must have keys matching the SanctionedEntity columns plus:
        aliases:      [{"alias_name", "alias_type", "is_primary"}]
        addresses:    [{"address", "city", "country", "postal_code"}]
        identifiers:  [{"id_type", "id_value", "country"}]
        vessels:      [{"vessel_name", "imo_number", "mmsi_number", "vessel_type",
                        "flag", "tonnage", "build_year", "call_sign"}]

    Returns (records_added, records_updated, records_removed).
    """
    result = await session.execute(
        select(SanctionedEntity.source_id).where(SanctionedEntity.source == source_name)
    )
    existing_ids: set[str] = {row[0] for row in result}
    incoming_ids: set[str] = set()

    records_added = 0
    records_updated = 0

    for batch_start in range(0, len(entities), batch_size):
        batch = entities[batch_start : batch_start + batch_size]

        for entity_dict in batch:
            source_id = entity_dict["source_id"]
            incoming_ids.add(source_id)
            is_update = source_id in existing_ids

            stmt = insert(SanctionedEntity).values(
                source=source_name,
                source_id=source_id,
                entity_type=entity_dict["entity_type"],
                primary_name=entity_dict["primary_name"],
                programs=entity_dict.get("programs"),
                legal_basis=entity_dict.get("legal_basis"),
                date_of_birth=entity_dict.get("date_of_birth"),
                nationality=entity_dict.get("nationality"),
                country_of_registration=entity_dict.get("country_of_registration"),
                remarks=entity_dict.get("remarks"),
                list_date=entity_dict.get("list_date"),
                data_vintage=entity_dict["data_vintage"],
                last_updated=entity_dict["last_updated"],
                raw_record=entity_dict.get("raw_record"),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["source", "source_id"],
                set_={
                    "entity_type": stmt.excluded.entity_type,
                    "primary_name": stmt.excluded.primary_name,
                    "programs": stmt.excluded.programs,
                    "legal_basis": stmt.excluded.legal_basis,
                    "date_of_birth": stmt.excluded.date_of_birth,
                    "nationality": stmt.excluded.nationality,
                    "country_of_registration": stmt.excluded.country_of_registration,
                    "remarks": stmt.excluded.remarks,
                    "list_date": stmt.excluded.list_date,
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
                    SanctionedEntity.source == source_name,
                    SanctionedEntity.source_id == source_id,
                )
            )
            entity_id = ent_result.scalar_one()

            await session.execute(delete(EntityAlias).where(EntityAlias.entity_id == entity_id))
            await session.execute(delete(EntityAddress).where(EntityAddress.entity_id == entity_id))
            await session.execute(
                delete(EntityIdentifier).where(EntityIdentifier.entity_id == entity_id)
            )
            await session.execute(delete(Vessel).where(Vessel.entity_id == entity_id))
            await session.execute(
                delete(EntityRelationship).where(EntityRelationship.from_entity_id == entity_id)
            )

            # Deduplicate aliases on (alias_name, alias_type) before inserting
            seen_aliases: set[tuple[str, str | None]] = set()
            for alias in entity_dict.get("aliases", []):
                alias_name = alias.get("alias_name")
                if alias_name:
                    key = (alias_name.lower(), alias.get("alias_type"))
                    if key not in seen_aliases:
                        seen_aliases.add(key)
                        session.add(
                            EntityAlias(
                                entity_id=entity_id,
                                alias_name=alias_name,
                                alias_type=alias.get("alias_type"),
                                is_primary=alias.get("is_primary", False),
                            )
                        )

            for addr in entity_dict.get("addresses", []):
                if any(addr.get(f) for f in ("address", "city", "country")):
                    session.add(
                        EntityAddress(
                            entity_id=entity_id,
                            address=addr.get("address"),
                            city=addr.get("city"),
                            country=addr.get("country"),
                            postal_code=addr.get("postal_code"),
                        )
                    )

            for ident in entity_dict.get("identifiers", []):
                session.add(
                    EntityIdentifier(
                        entity_id=entity_id,
                        id_type=ident["id_type"],
                        id_value=ident["id_value"],
                        country=ident.get("country"),
                    )
                )

            for vessel in entity_dict.get("vessels", []):
                session.add(
                    Vessel(
                        entity_id=entity_id,
                        vessel_name=vessel.get("vessel_name"),
                        imo_number=vessel.get("imo_number"),
                        mmsi_number=vessel.get("mmsi_number"),
                        vessel_type=vessel.get("vessel_type"),
                        flag=vessel.get("flag"),
                        tonnage=vessel.get("tonnage"),
                        build_year=vessel.get("build_year"),
                        call_sign=vessel.get("call_sign"),
                    )
                )

        await session.flush()

    removed_ids = existing_ids - incoming_ids
    records_removed = len(removed_ids)
    if removed_ids:
        await session.execute(
            delete(SanctionedEntity).where(
                SanctionedEntity.source == source_name,
                SanctionedEntity.source_id.in_(removed_ids),
            )
        )
        logger.info("records_removed", source=source_name, count=records_removed)

    return records_added, records_updated, records_removed
