from __future__ import annotations


class IngestionError(Exception):
    """Base exception for ingestion pipeline errors."""


class RecordParseError(IngestionError):
    """Raised when a single record cannot be parsed."""

    def __init__(self, source_id: str, reason: str) -> None:
        self.source_id = source_id
        self.reason = reason
        super().__init__(f"Failed to parse record {source_id}: {reason}")
