"""Backfill embeddings for document_chunks rows that have NULL embeddings.

Designed for memory-constrained environments: loads the embedding model once,
then processes chunks in small batches with explicit memory cleanup between batches.

Usage:
    docker run --rm --add-host=host.docker.internal:host-gateway \
      --memory=6g \
      -e SSA_DATABASE_URL="..." \
      -e SSA_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
      -e SSA_EMBEDDING_DIM=384 \
      -e BACKFILL_BATCH_SIZE=25 \
      sanctions-ingestion uv run python scripts/backfill_embeddings.py
"""

from __future__ import annotations

import asyncio
import gc
import os
import sys
import time

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline.db import async_session_factory
from pipeline.db_models import DocumentChunk
from pipeline.embeddings import EmbeddingModel

logger = structlog.get_logger()

BATCH_SIZE = int(os.environ.get("BACKFILL_BATCH_SIZE", "25"))


async def backfill(session: AsyncSession, embedder: EmbeddingModel) -> int:
    total_null = await session.scalar(
        select(func.count()).where(DocumentChunk.embedding.is_(None))
    )
    if total_null == 0:
        logger.info("no_null_embeddings_found")
        return 0

    logger.info("backfill_started", total_null_embeddings=total_null, batch_size=BATCH_SIZE)
    total_embedded = 0
    start = time.perf_counter()

    while True:
        rows = (
            await session.execute(
                select(DocumentChunk.id, DocumentChunk.content)
                .where(DocumentChunk.embedding.is_(None))
                .limit(BATCH_SIZE)
            )
        ).all()

        if not rows:
            break

        ids = [r.id for r in rows]
        texts = [r.content for r in rows]

        vectors = embedder.embed_batch(texts, batch_size=BATCH_SIZE)

        for chunk_id, vector in zip(ids, vectors, strict=True):
            await session.execute(
                update(DocumentChunk)
                .where(DocumentChunk.id == chunk_id)
                .values(embedding=vector)
            )

        await session.commit()
        total_embedded += len(rows)

        gc.collect()

        elapsed = time.perf_counter() - start
        logger.info(
            "backfill_progress",
            embedded=total_embedded,
            total=total_null,
            elapsed_seconds=round(elapsed, 1),
        )

    elapsed = time.perf_counter() - start
    logger.info(
        "backfill_completed",
        total_embedded=total_embedded,
        elapsed_seconds=round(elapsed, 1),
        chunks_per_second=round(total_embedded / elapsed, 1) if elapsed > 0 else 0,
    )
    return total_embedded


async def main() -> int:
    logger.info(
        "starting_embedding_backfill",
        batch_size=BATCH_SIZE,
    )

    embedder = EmbeddingModel()

    async with async_session_factory() as session:
        total = await backfill(session, embedder)

    if total == 0:
        logger.info("nothing_to_backfill")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
