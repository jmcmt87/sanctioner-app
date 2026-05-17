"""Run OFAC FAQ ingestion as a standalone script."""

from __future__ import annotations

import asyncio
import sys

import structlog

from pipeline.config import config
from pipeline.db import async_session_factory
from pipeline.sources.ofac_faq import ingest_ofac_faqs

logger = structlog.get_logger()


async def main() -> int:
    logger.info("starting_ofac_faq_ingestion", data_dir=str(config.data_dir))

    async with async_session_factory() as session:
        result = await ingest_ofac_faqs(session=session, data_dir=config.data_dir)

    logger.info(
        "ingestion_result",
        source=result.source,
        status=result.status,
        records_processed=result.records_processed,
        records_added=result.records_added,
        records_skipped=result.records_skipped,
        duration_seconds=(result.completed_at - result.started_at).total_seconds(),
    )

    if result.status == "failed":
        logger.error("ingestion_failed", error_message=result.error_message)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
