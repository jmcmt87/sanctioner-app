"""Extract entity relationships from OFAC remarks and populate entity_relationships.

Parses "Linked To:" references in OFAC SDN/Non-SDN remarks fields, resolves them
against known entities (by primary_name or alias), and creates entity_relationships
records with relationship_type='linked_to'.
"""

from __future__ import annotations

import re

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline.db_models import EntityAlias, EntityRelationship, SanctionedEntity

logger = structlog.get_logger()

LINKED_TO_RE = re.compile(r"Linked To:\s*([^;.]+?)(?:\s*,\s*source_id\s*\d+)?(?:[;.]|$)")


def extract_linked_names(remarks: str) -> list[str]:
    """Extract entity names from 'Linked To:' patterns in OFAC remarks.

    Returns a list of entity names with trailing whitespace/punctuation stripped.
    """
    return [match.strip() for match in LINKED_TO_RE.findall(remarks) if match.strip()]


async def resolve_relationships(session: AsyncSession) -> tuple[int, int]:
    """Extract 'Linked To:' from OFAC remarks and populate entity_relationships.

    Idempotent: deletes all existing 'ofac_remarks' relationships before re-creating.

    Returns (resolved_count, unresolved_count).
    """
    # Delete existing relationships from this source for idempotent re-runs
    await session.execute(
        delete(EntityRelationship).where(EntityRelationship.source == "ofac_remarks")
    )
    await session.flush()

    # Query all OFAC entities with "Linked To:" in remarks
    result = await session.execute(
        select(SanctionedEntity.id, SanctionedEntity.remarks).where(
            SanctionedEntity.source.in_(["ofac_sdn", "ofac_nonsdn"]),
            SanctionedEntity.remarks.ilike("%Linked To:%"),
        )
    )
    entities_with_links = result.all()

    logger.info("linked_to_scan", entities_with_references=len(entities_with_links))

    resolved_count = 0
    unresolved_count = 0
    total_references = 0

    for from_entity_id, remarks in entities_with_links:
        linked_names = extract_linked_names(remarks)
        total_references += len(linked_names)

        for name in linked_names:
            # Try exact match on primary_name (case-insensitive)
            target_result = await session.execute(
                select(SanctionedEntity.id).where(
                    func.lower(SanctionedEntity.primary_name) == name.lower()
                )
            )
            target_id = target_result.scalar()

            # If no match by primary_name, try aliases
            if target_id is None:
                alias_result = await session.execute(
                    select(EntityAlias.entity_id).where(
                        func.lower(EntityAlias.alias_name) == name.lower()
                    )
                )
                target_id = alias_result.scalar()

            if target_id is None:
                logger.debug(
                    "linked_to_unresolved",
                    from_entity_id=str(from_entity_id),
                    linked_name=name,
                )
                unresolved_count += 1
                continue

            # Skip self-references
            if target_id == from_entity_id:
                continue

            # Insert with ON CONFLICT DO NOTHING for the unique constraint
            stmt = insert(EntityRelationship).values(
                from_entity_id=from_entity_id,
                to_entity_id=target_id,
                relationship_type="linked_to",
                source="ofac_remarks",
                notes=f"Linked To: {name}",
            )
            stmt = stmt.on_conflict_do_nothing(constraint="uq_entity_relationships_from_to_type")
            await session.execute(stmt)
            resolved_count += 1

    await session.flush()

    logger.info(
        "linked_to_resolution_complete",
        total_references=total_references,
        resolved=resolved_count,
        unresolved=unresolved_count,
    )

    return resolved_count, unresolved_count
