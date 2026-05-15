from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


def compute_record_hash(record: dict[str, Any]) -> str:
    """Deterministic hash of a record for change detection."""
    normalized = json.dumps(record, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode()).hexdigest()


def compute_file_hash(path: Path) -> str:
    """SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_source_hash(source_dir: Path, file_patterns: list[str]) -> str:
    """Compute combined hash of all source files for change detection."""
    h = hashlib.sha256()
    for pattern in sorted(file_patterns):
        for path in sorted(source_dir.glob(pattern)):
            h.update(compute_file_hash(path).encode())
    return h.hexdigest()


class HashStore:
    """Tracks file hashes to detect changes between ingestion runs."""

    def __init__(self, store_path: Path) -> None:
        self._path = store_path
        self._hashes: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            self._hashes = json.loads(self._path.read_text())

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._hashes, indent=2))

    def has_changed(self, source_name: str, current_hash: str) -> bool:
        previous = self._hashes.get(source_name)
        return previous != current_hash

    def update(self, source_name: str, current_hash: str) -> None:
        self._hashes[source_name] = current_hash
        self._save()
        logger.info("hash_updated", source=source_name, hash=current_hash[:12])
