from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline.chunking.text_chunker import ChunkResult
from pipeline.db_models import DocumentChunk

logger = structlog.get_logger()


async def store_document_chunks(
    session: AsyncSession,
    chunks: list[ChunkResult],
    embeddings: list[list[float]],
    source_document: str,
    metadata: dict | None = None,
) -> int:
    """Store document chunks with embeddings, replacing any existing chunks for this document."""
    if len(chunks) != len(embeddings):
        msg = f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) must have equal length"
        raise ValueError(msg)

    existing = await session.execute(
        select(DocumentChunk.id).where(DocumentChunk.source_document == source_document)
    )
    existing_count = len(existing.all())
    if existing_count > 0:
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.source_document == source_document)
        )
        logger.info(
            "existing_chunks_deleted",
            source_document=source_document,
            count=existing_count,
        )

    now = datetime.now(UTC)
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        meta = chunk.metadata
        session.add(
            DocumentChunk(
                content=chunk.content,
                embedding=embedding,
                source_document=meta.source_document,
                source_title=meta.source_title,
                jurisdiction=meta.jurisdiction,
                document_type=meta.document_type,
                article_reference=None,
                chunk_index=chunk.chunk_index,
                published_date=meta.published_date,
                ingestion_timestamp=now,
                data_vintage=meta.data_vintage,
                metadata_=metadata,
            )
        )

    await session.flush()

    logger.info(
        "chunks_stored",
        source_document=source_document,
        count=len(chunks),
    )

    return len(chunks)
