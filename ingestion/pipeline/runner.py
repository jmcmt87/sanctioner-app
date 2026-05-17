from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline.db import async_session_factory
from pipeline.hashing import HashStore, compute_source_hash
from pipeline.models import IngestionResult
from pipeline.relationships import resolve_relationships
from pipeline.sources.enforcement import ingest_enforcement_pdfs
from pipeline.sources.eu_regulation import ingest_eu_regulations
from pipeline.sources.eu_sanctions import ingest_eu_sanctions
from pipeline.sources.general_licenses import ingest_general_licenses
from pipeline.sources.guidance import ingest_guidance_docs
from pipeline.sources.ofac_faq import ingest_ofac_faqs
from pipeline.sources.ofac_nonsdn import ingest_ofac_nonsdn
from pipeline.sources.ofac_sdn import ingest_ofac_sdn

logger = structlog.get_logger()

SourceHandler = Callable[[AsyncSession, Path], Coroutine[Any, Any, IngestionResult]]

REGISTERED_SOURCES: dict[str, SourceHandler] = {
    "ofac_sdn": ingest_ofac_sdn,
    "ofac_nonsdn": ingest_ofac_nonsdn,
    "eu_consolidated": ingest_eu_sanctions,
    "enforcement": ingest_enforcement_pdfs,
    "guidance": ingest_guidance_docs,
    "general_licenses": ingest_general_licenses,
    "ofac_faq": ingest_ofac_faqs,
    "eu_regulation": ingest_eu_regulations,
}

SOURCE_FILES: dict[str, list[str]] = {
    "ofac_sdn": ["ofac_sdn/*.csv"],
    "ofac_nonsdn": ["ofac_nonsdn/*.csv"],
    "eu_consolidated": ["eu_consolidated/*.xml"],
    "enforcement": ["enforcement/*.pdf"],
    "guidance": ["guidance/*.pdf"],
    "general_licenses": ["general_licenses/*.pdf"],
    "ofac_faq": ["ofac_faq/*.pdf"],
    "eu_regulation": ["eu_regulation/*.pdf"],
}


async def run_ingestion(
    data_dir: Path,
    sources: list[str] | None = None,
    skip_unchanged: bool = True,
) -> list[IngestionResult]:
    """Run ingestion for specified sources (or all registered sources)."""
    targets = sources or list(REGISTERED_SOURCES.keys())
    results: list[IngestionResult] = []

    hash_store = HashStore(data_dir / ".ingestion_hashes.json")

    for name in targets:
        handler = REGISTERED_SOURCES.get(name)
        if not handler:
            logger.error("unknown_source", source=name)
            continue

        log = logger.bind(source=name)

        if skip_unchanged and name in SOURCE_FILES:
            current_hash = compute_source_hash(data_dir, SOURCE_FILES[name])
            if not hash_store.has_changed(name, current_hash):
                log.info("source_unchanged_skipping")
                now = datetime.now(UTC)
                results.append(
                    IngestionResult(
                        source=name,
                        ingestion_type="incremental",
                        started_at=now,
                        completed_at=now,
                        records_processed=0,
                        records_added=0,
                        records_updated=0,
                        records_removed=0,
                        records_skipped=0,
                        status="skipped_unchanged",
                    )
                )
                continue

        async with async_session_factory() as session:
            result = await handler(session, data_dir)
            results.append(result)

        if result.status in ("completed", "completed_with_errors") and name in SOURCE_FILES:
            current_hash = compute_source_hash(data_dir, SOURCE_FILES[name])
            hash_store.update(name, current_hash)

        log.info(
            "source_ingestion_complete",
            status=result.status,
            added=result.records_added,
            updated=result.records_updated,
            removed=result.records_removed,
        )

    # Resolve "Linked To:" relationships after all sources are ingested
    # so entities from all sources (SDN, Non-SDN, EU) are available for resolution.
    async with async_session_factory() as session:
        logger.info("resolving_relationships")
        resolved, unresolved = await resolve_relationships(session)
        logger.info("relationships_resolved", resolved=resolved, unresolved=unresolved)
        await session.commit()

    return results
