"""Run incremental ingestion — skips sources whose files haven't changed."""

from __future__ import annotations

import asyncio
import sys

import structlog

from pipeline.config import config
from pipeline.runner import run_ingestion

logger = structlog.get_logger()


async def main() -> int:
    logger.info("starting_incremental_ingestion", data_dir=str(config.data_dir))

    results = await run_ingestion(
        data_dir=config.data_dir,
        skip_unchanged=True,
    )

    for result in results:
        logger.info(
            "source_result",
            source=result.source,
            status=result.status,
            added=result.records_added,
            updated=result.records_updated,
            removed=result.records_removed,
            skipped=result.records_skipped,
        )

    failed = [r for r in results if r.status == "failed"]
    if failed:
        logger.error("ingestion_has_failures", count=len(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
