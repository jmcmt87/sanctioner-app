from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog

from pipeline.config import IngestionConfig
from pipeline.hashing import compute_content_hash
from pipeline.models import AcquisitionResult

logger = structlog.get_logger()

USER_AGENT = "SanctionsScreeningAssistant/1.0 (compliance-research-tool)"


async def download_file(
    url: str,
    dest: Path,
    max_retries: int = 3,
) -> bytes:
    """Download a file with retry logic. Returns file content."""
    log = logger.bind(url=url)
    dest.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=10.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for attempt in range(1, max_retries + 1):
            try:
                response = await client.get(url)
                response.raise_for_status()
                content = response.content
                await asyncio.to_thread(dest.write_bytes, content)
                log.info("file_downloaded", size_bytes=len(content), dest=str(dest))
                return content
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                if attempt == max_retries:
                    log.error("download_failed", attempts=attempt, error=str(e))
                    raise
                delay = 2**attempt
                log.warning(
                    "download_retry",
                    attempt=attempt,
                    delay=delay,
                    error=str(e),
                )
                await asyncio.sleep(delay)

    msg = "unreachable"
    raise RuntimeError(msg)


def s3_key(category: str, source_name: str, filename: str, date: datetime | None = None) -> str:
    """Build S3 key: raw/{category}/{source_name}/{YYYY-MM-DD}/{filename}"""
    d = (date or datetime.now(UTC)).strftime("%Y-%m-%d")
    return f"raw/{category}/{source_name}/{d}/{filename}"


class S3Client:
    """Wrapper around boto3 S3 client for raw document storage."""

    def __init__(self, config: IngestionConfig) -> None:
        self.bucket = config.s3_bucket
        self._config = config
        self._client = self._create_client()

    def _create_client(self) -> Any:
        import boto3

        kwargs: dict = {"region_name": self._config.s3_region}
        if self._config.aws_access_key_id:
            kwargs["aws_access_key_id"] = self._config.aws_access_key_id
            kwargs["aws_secret_access_key"] = self._config.aws_secret_access_key
        return boto3.client("s3", **kwargs)

    def upload_bytes(
        self, key: str, content: bytes, metadata: dict[str, str] | None = None
    ) -> None:
        extra: dict = {}
        if metadata:
            extra["Metadata"] = metadata
        self._client.put_object(Bucket=self.bucket, Key=key, Body=content, **extra)
        logger.info("s3_upload", bucket=self.bucket, key=key, size_bytes=len(content))

    def download_bytes(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self.bucket, Key=key)
        content = response["Body"].read()
        logger.info("s3_download", bucket=self.bucket, key=key, size_bytes=len(content))
        return content

    def get_metadata(self, key: str) -> dict[str, str]:
        try:
            response = self._client.head_object(Bucket=self.bucket, Key=key)
            return response.get("Metadata", {})
        except self._client.exceptions.ClientError:
            return {}

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def get_latest_key(self, prefix: str) -> str | None:
        keys = self.list_keys(prefix)
        return sorted(keys)[-1] if keys else None

    def has_changed(self, prefix: str, new_hash: str) -> bool:
        """Check if the file has changed since the last upload by comparing SHA-256 hashes."""
        latest = self.get_latest_key(prefix)
        if not latest:
            return True
        metadata = self.get_metadata(latest)
        return metadata.get("sha256", "") != new_hash


async def acquire_direct_download(
    url: str,
    source_name: str,
    category: str,
    filename: str,
    local_dir: Path,
    s3_client: S3Client | None = None,
) -> AcquisitionResult:
    """Download a file, optionally upload to S3 with hash-based change detection."""
    log = logger.bind(source=source_name)
    fetch_timestamp = datetime.now(UTC)
    dest = local_dir / filename

    content = await download_file(url, dest)
    file_hash = compute_content_hash(content)

    changed = True
    s3_dest_key: str | None = None

    if s3_client:
        prefix = f"raw/{category}/{source_name}/"
        changed = s3_client.has_changed(prefix, file_hash)
        if changed:
            s3_dest_key = s3_key(category, source_name, filename, fetch_timestamp)
            s3_client.upload_bytes(s3_dest_key, content, metadata={"sha256": file_hash})
            log.info("s3_uploaded_new_version", key=s3_dest_key)
        else:
            log.info("s3_unchanged_skipping", source=source_name, filename=filename)

    return AcquisitionResult(
        source_name=source_name,
        local_path=str(dest),
        s3_key=s3_dest_key,
        fetch_timestamp=fetch_timestamp,
        file_hash=file_hash,
        changed=changed,
    )
