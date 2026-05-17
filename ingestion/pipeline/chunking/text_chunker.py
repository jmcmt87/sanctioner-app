"""Text chunking module for the ingestion pipeline.

Wraps langchain's RecursiveCharacterTextSplitter with domain-specific
metadata validation and quality warnings.
"""

from __future__ import annotations

from datetime import date, datetime

import structlog
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel

logger = structlog.get_logger()

VALID_JURISDICTIONS = {"US", "EU", "DE"}
VALID_DOCUMENT_TYPES = {"enforcement", "regulation", "guidance", "faq", "general_license"}

_MIN_CHUNK_CHARS = 100
_MAX_CHUNK_CHARS = 3500


class ChunkMetadata(BaseModel):
    source_document: str
    source_title: str
    jurisdiction: str
    document_type: str
    published_date: date | None
    data_vintage: datetime


class ChunkResult(BaseModel):
    content: str
    chunk_index: int
    metadata: ChunkMetadata


class TextChunker:
    def __init__(
        self,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
    ) -> None:
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def chunk_document(self, text: str, metadata: ChunkMetadata) -> list[ChunkResult]:
        self._validate_metadata(metadata)

        if not text or not text.strip():
            return []

        splits = self._splitter.split_text(text)

        chunks: list[ChunkResult] = []
        idx = 0
        for split in splits:
            if len(split) < _MIN_CHUNK_CHARS:
                logger.info(
                    "runt_chunk_filtered",
                    source=metadata.source_document,
                    length=len(split),
                    preview=split[:80],
                )
                continue
            chunks.append(ChunkResult(content=split, chunk_index=idx, metadata=metadata))
            idx += 1

        self._log_chunk_stats(chunks, metadata.source_document)

        return chunks

    def _validate_metadata(self, metadata: ChunkMetadata) -> None:
        if not metadata.source_document:
            msg = "source_document is required"
            raise ValueError(msg)
        if not metadata.source_title:
            msg = "source_title is required"
            raise ValueError(msg)
        if metadata.jurisdiction not in VALID_JURISDICTIONS:
            msg = (
                f"Invalid jurisdiction '{metadata.jurisdiction}'. "
                f"Must be one of: {sorted(VALID_JURISDICTIONS)}"
            )
            raise ValueError(msg)
        if metadata.document_type not in VALID_DOCUMENT_TYPES:
            msg = (
                f"Invalid document_type '{metadata.document_type}'. "
                f"Must be one of: {sorted(VALID_DOCUMENT_TYPES)}"
            )
            raise ValueError(msg)

    def _log_chunk_stats(self, chunks: list[ChunkResult], source: str) -> None:
        if not chunks:
            return

        lengths = [len(c.content) for c in chunks]
        avg_length = sum(lengths) / len(lengths)

        logger.info(
            "document_chunked",
            source=source,
            chunk_count=len(chunks),
            avg_chunk_length=round(avg_length),
        )

        for chunk in chunks:
            length = len(chunk.content)
            if length > _MAX_CHUNK_CHARS:
                logger.warning(
                    "long_chunk_detected",
                    source=source,
                    chunk_index=chunk.chunk_index,
                    length=length,
                )
