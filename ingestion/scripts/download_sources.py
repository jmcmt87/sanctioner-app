"""Download all structured sanctions list source files from government websites.

Fetches OFAC SDN, OFAC Non-SDN, and EU Consolidated Financial Sanctions List.
Uses SHA-256 hash comparison to detect changes — re-downloading unchanged
files is a no-op.

Usage:
    uv run python scripts/download_sources.py
    uv run python scripts/download_sources.py --source ofac_sdn
    uv run python scripts/download_sources.py --source ofac_nonsdn
    uv run python scripts/download_sources.py --source eu_consolidated
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import structlog

from pipeline.acquisition import (
    acquire_all_sources,
    acquire_eu_sanctions,
    acquire_ofac_nonsdn,
    acquire_ofac_sdn,
)
from pipeline.config import config
from pipeline.hashing import HashStore

logger = structlog.get_logger()

SOURCE_FUNCTIONS = {
    "ofac_sdn": acquire_ofac_sdn,
    "ofac_nonsdn": acquire_ofac_nonsdn,
    "eu_consolidated": acquire_eu_sanctions,
}


async def main() -> int:
    parser = argparse.ArgumentParser(description="Download structured sanctions list source files.")
    parser.add_argument(
        "--source",
        choices=list(SOURCE_FUNCTIONS.keys()),
        help="Download only the specified source. If omitted, downloads all.",
    )
    args = parser.parse_args()

    data_dir = config.data_dir
    logger.info("download_sources_started", data_dir=str(data_dir), source=args.source or "all")

    if args.source:
        hash_store = HashStore(data_dir / ".acquisition_hashes.json")
        result = await SOURCE_FUNCTIONS[args.source](data_dir, hash_store)
        results = [result]
    else:
        results = await acquire_all_sources(data_dir)

    has_failure = False
    for result in results:
        if result.files_downloaded == 0 and result.files_discovered > 0:
            logger.error(
                "source_download_failed",
                source=result.source_name,
            )
            has_failure = True
        elif result.changed:
            logger.info(
                "source_updated",
                source=result.source_name,
                files_downloaded=result.files_downloaded,
                hash=result.file_hash[:12] if result.file_hash else None,
            )
        else:
            logger.info(
                "source_unchanged",
                source=result.source_name,
                hash=result.file_hash[:12] if result.file_hash else None,
            )

    if has_failure:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
