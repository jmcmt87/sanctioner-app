"""Automated data acquisition for structured sanctions list sources.

Downloads fresh source files from government websites with hash-based
change detection to skip re-ingestion when sources haven't changed.
Stores timestamped copies in data/{source}/archive/ for audit trail.
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
import structlog

from pipeline.hashing import HashStore, compute_content_hash
from pipeline.models import AcquisitionResult

logger = structlog.get_logger()

USER_AGENT = "SanctionsScreeningAssistant/1.0 (compliance-research-tool)"
MAX_RETRIES = 3

OFAC_SDN_FILES: dict[str, str] = {
    "sdn.csv": "https://www.treasury.gov/ofac/downloads/sdn.csv",
    "add.csv": "https://www.treasury.gov/ofac/downloads/add.csv",
    "alt.csv": "https://www.treasury.gov/ofac/downloads/alt.csv",
    "sdn_comments.csv": "https://www.treasury.gov/ofac/downloads/sdn_comments.csv",
}

OFAC_NONSDN_FILES: dict[str, str] = {
    "cons_prim.csv": "https://www.treasury.gov/ofac/downloads/consolidated/cons_prim.csv",
    "cons_add.csv": "https://www.treasury.gov/ofac/downloads/consolidated/cons_add.csv",
    "cons_alt.csv": "https://www.treasury.gov/ofac/downloads/consolidated/cons_alt.csv",
    "cons_comments.csv": "https://www.treasury.gov/ofac/downloads/consolidated/cons_comments.csv",
}

EU_SANCTIONS_FILES: dict[str, str] = {
    "eu_sanctions_list.xml": (
        "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content"
        "?token=dG9rZW4tMjAxNw"
    ),
}


async def _download_with_retry(
    client: httpx.AsyncClient,
    url: str,
    max_retries: int = MAX_RETRIES,
) -> bytes:
    """Download a URL with retry and exponential backoff. Returns content bytes."""
    for attempt in range(1, max_retries + 1):
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.content
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            if attempt == max_retries:
                raise
            delay = 2**attempt
            logger.warning(
                "download_retry",
                url=url,
                attempt=attempt,
                delay=delay,
                error=str(e),
            )
            await asyncio.sleep(delay)

    msg = "unreachable"
    raise RuntimeError(msg)


def _archive_file(file_path: Path, archive_dir: Path, timestamp: datetime) -> Path:
    """Copy a file to the archive directory with a timestamp prefix."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = timestamp.strftime("%Y%m%dT%H%M%SZ")
    archived = archive_dir / f"{ts}_{file_path.name}"
    shutil.copy2(file_path, archived)
    return archived


async def _acquire_source_files(
    source_name: str,
    files: dict[str, str],
    dest_dir: Path,
    hash_store: HashStore,
) -> AcquisitionResult:
    """Download a set of files for a source, using combined hash for change detection."""
    log = logger.bind(source=source_name)
    fetch_timestamp = datetime.now(UTC)
    await asyncio.to_thread(dest_dir.mkdir, parents=True, exist_ok=True)
    archive_dir = dest_dir / "archive"

    log.info("acquisition_started", file_count=len(files))

    downloaded_content: dict[str, bytes] = {}
    errors: list[str] = []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=10.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for filename, url in files.items():
            try:
                content = await _download_with_retry(client, url)
                downloaded_content[filename] = content
                log.info(
                    "file_downloaded",
                    filename=filename,
                    size_bytes=len(content),
                )
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                errors.append(f"{filename}: {e}")
                log.error(
                    "file_download_failed",
                    filename=filename,
                    url=url,
                    error=str(e),
                )
            await asyncio.sleep(1.0)

    if not downloaded_content:
        log.error("all_downloads_failed", errors=errors)
        return AcquisitionResult(
            source_name=source_name,
            local_path=None,
            fetch_timestamp=fetch_timestamp,
            file_hash=None,
            changed=False,
            files_discovered=len(files),
            files_downloaded=0,
        )

    combined_hash = compute_content_hash(
        b"".join(downloaded_content[k] for k in sorted(downloaded_content.keys()))
    )

    changed = hash_store.has_changed(source_name, combined_hash)

    if not changed:
        log.info("source_unchanged", hash=combined_hash[:12])
        return AcquisitionResult(
            source_name=source_name,
            local_path=str(dest_dir),
            fetch_timestamp=fetch_timestamp,
            file_hash=combined_hash,
            changed=False,
            files_discovered=len(files),
            files_downloaded=len(downloaded_content),
        )

    for filename, content in downloaded_content.items():
        file_path = dest_dir / filename
        file_path.write_bytes(content)
        _archive_file(file_path, archive_dir, fetch_timestamp)

    hash_store.update(source_name, combined_hash)

    log.info(
        "source_updated",
        files_written=len(downloaded_content),
        hash=combined_hash[:12],
        errors=len(errors),
    )

    return AcquisitionResult(
        source_name=source_name,
        local_path=str(dest_dir),
        fetch_timestamp=fetch_timestamp,
        file_hash=combined_hash,
        changed=True,
        files_discovered=len(files),
        files_downloaded=len(downloaded_content),
    )


async def acquire_ofac_sdn(data_dir: Path, hash_store: HashStore) -> AcquisitionResult:
    """Download OFAC SDN list files from Treasury.gov."""
    return await _acquire_source_files(
        source_name="ofac_sdn",
        files=OFAC_SDN_FILES,
        dest_dir=data_dir / "ofac_sdn",
        hash_store=hash_store,
    )


async def acquire_ofac_nonsdn(data_dir: Path, hash_store: HashStore) -> AcquisitionResult:
    """Download OFAC Non-SDN (Consolidated) list files from Treasury.gov."""
    return await _acquire_source_files(
        source_name="ofac_nonsdn",
        files=OFAC_NONSDN_FILES,
        dest_dir=data_dir / "ofac_nonsdn",
        hash_store=hash_store,
    )


async def acquire_eu_sanctions(data_dir: Path, hash_store: HashStore) -> AcquisitionResult:
    """Download EU Consolidated Financial Sanctions List XML from European Commission."""
    return await _acquire_source_files(
        source_name="eu_consolidated",
        files=EU_SANCTIONS_FILES,
        dest_dir=data_dir / "eu_consolidated",
        hash_store=hash_store,
    )


async def acquire_all_sources(data_dir: Path) -> list[AcquisitionResult]:
    """Download all structured sanctions list sources with change detection.

    Returns a list of AcquisitionResult for each source.
    """
    hash_store = HashStore(data_dir / ".acquisition_hashes.json")

    results = [
        await acquire_ofac_sdn(data_dir, hash_store),
        await acquire_ofac_nonsdn(data_dir, hash_store),
        await acquire_eu_sanctions(data_dir, hash_store),
    ]

    changed_count = sum(1 for r in results if r.changed)
    failed_count = sum(1 for r in results if r.files_downloaded == 0)

    logger.info(
        "acquisition_complete",
        total_sources=len(results),
        changed=changed_count,
        unchanged=len(results) - changed_count - failed_count,
        failed=failed_count,
    )

    return results
