from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class IngestionResult(BaseModel):
    source: str
    ingestion_type: str
    started_at: datetime
    completed_at: datetime
    records_processed: int
    records_added: int
    records_updated: int
    records_removed: int
    records_skipped: int
    status: str
    error_message: str | None = None
    source_vintage: datetime | None = None


class AcquisitionResult(BaseModel):
    source_name: str
    local_path: str | None = None
    s3_key: str | None = None
    fetch_timestamp: datetime
    source_vintage: datetime | None = None
    file_hash: str | None = None
    changed: bool
    files_discovered: int = 0
    files_downloaded: int = 0
