from __future__ import annotations

import gc
from datetime import UTC, date, datetime
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline.chunking.regulation_chunker import RegulationChunker, RegulationChunkResult
from pipeline.chunking.text_chunker import ChunkMetadata, ChunkResult
from pipeline.db_models import IngestionLog
from pipeline.embeddings import EmbeddingModel
from pipeline.extraction import extract_pdf
from pipeline.loaders import download_file
from pipeline.models import IngestionResult

logger = structlog.get_logger()

SOURCE_NAME = "eu_regulation"

EU_REGULATION_MANIFEST: dict[str, dict] = {
    "reg_833_2014": {
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:02014R0833-20260424",
        "title": "Council Regulation (EU) No 833/2014 - Consolidated",
        "published_date": date(2014, 7, 31),
        "jurisdiction": "EU",
    },
    "reg_269_2014": {
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:02014R0269-20250916",
        "title": "Council Regulation (EU) No 269/2014 - Consolidated",
        "published_date": date(2014, 3, 17),
        "jurisdiction": "EU",
    },
}

CRITICAL_ARTICLES_833 = [
    "Article 3a",
    "Article 3m",
    "Article 3n",
    "Article 5",
    "Article 5a",
    "Article 5aa",
    "Article 5b",
    "Article 5e",
    "Article 5f",
    "Article 5g",
    "Article 5h",
    "Article 5k",
    "Article 5n",
    "Article 11",
    "Article 12",
]

MIN_EXTRACTION_QUALITY = 0.4


def _convert_regulation_chunks(chunks: list[RegulationChunkResult]) -> list[ChunkResult]:
    """Convert RegulationChunkResult to ChunkResult for store_document_chunks compatibility."""
    results: list[ChunkResult] = []
    for chunk in chunks:
        meta = ChunkMetadata(
            source_document=chunk.metadata.source_document,
            source_title=chunk.metadata.source_title,
            jurisdiction=chunk.metadata.jurisdiction,
            document_type=chunk.metadata.document_type,
            published_date=chunk.metadata.published_date,
            data_vintage=chunk.metadata.data_vintage,
        )
        results.append(
            ChunkResult(content=chunk.content, chunk_index=chunk.chunk_index, metadata=meta)
        )
    return results


async def ingest_eu_regulations(
    session: AsyncSession,
    data_dir: Path,
) -> IngestionResult:
    """Ingest EU regulation texts with structure-aware chunking."""
    started_at = datetime.now(UTC)
    source_dir = data_dir / "eu_regulation"
    source_dir.mkdir(parents=True, exist_ok=True)

    log = logger.bind(source=SOURCE_NAME)
    log.info(
        "ingestion_started",
        data_dir=str(source_dir),
        manifest_count=len(EU_REGULATION_MANIFEST),
    )

    chunker = RegulationChunker()
    embedder = EmbeddingModel()

    records_processed = 0
    records_added = 0
    records_skipped = 0
    error_message: str | None = None
    status = "completed"

    for slug, entry in EU_REGULATION_MANIFEST.items():
        pdf_path = source_dir / f"{slug}.pdf"
        pdf_log = log.bind(slug=slug, path=str(pdf_path))

        try:
            if pdf_path.exists():
                pdf_log.info("pdf_already_exists_skipping_download")
            else:
                await download_file(entry["url"], pdf_path)
                pdf_log.info("pdf_downloaded")

            header = pdf_path.read_bytes()[:5]
            if header != b"%PDF-":
                pdf_log.warning("not_a_pdf", header=header[:20].hex())
                pdf_path.unlink()
                records_skipped += 1
                continue

            extracted = await extract_pdf(pdf_path)

            if extracted.extraction_quality < MIN_EXTRACTION_QUALITY:
                pdf_log.warning(
                    "low_extraction_quality_skipping",
                    extraction_quality=round(extracted.extraction_quality, 3),
                )
                records_skipped += 1
                continue

            data_vintage = datetime.now(UTC)
            source_document = f"eu_regulation/{slug}.pdf"

            reg_chunks = chunker.chunk_regulation(
                text=extracted.text,
                source_document=source_document,
                source_title=entry["title"],
                jurisdiction=entry["jurisdiction"],
                published_date=entry["published_date"],
                data_vintage=data_vintage,
            )

            if not reg_chunks:
                pdf_log.warning("no_chunks_produced")
                records_skipped += 1
                continue

            # Validate critical article coverage for 833/2014
            if slug == "reg_833_2014":
                found_articles = {
                    c.metadata.article_reference for c in reg_chunks if c.metadata.article_reference
                }
                missing = [a for a in CRITICAL_ARTICLES_833 if a not in found_articles]
                if missing:
                    pdf_log.warning("missing_critical_articles", missing=missing)

            # Convert to ChunkResult for store_document_chunks
            chunks = _convert_regulation_chunks(reg_chunks)

            # Embed in sub-batches to avoid OOM on large regulations (8GB RAM system)
            embed_batch_size = 100
            embeddings: list[list[float]] = []
            for i in range(0, len(chunks), embed_batch_size):
                batch = chunks[i : i + embed_batch_size]
                batch_embeddings = embedder.embed_batch(
                    [c.content for c in batch], batch_size=8
                )
                embeddings.extend(batch_embeddings)

            # Store with article_reference in metadata
            article_refs = {c.chunk_index: c.metadata.article_reference for c in reg_chunks}
            stored = await _store_regulation_chunks(
                session, chunks, embeddings, source_document, article_refs
            )

            records_added += stored
            records_processed += 1

            # Commit and free memory between regulations to avoid OOM
            await session.commit()
            del chunks, embeddings, reg_chunks, extracted
            gc.collect()

            pdf_log.info(
                "regulation_ingested",
                chunks_stored=stored,
                articles_found=len(found_articles) if slug == "reg_833_2014" else None,
            )

        except Exception:
            records_skipped += 1
            pdf_log.exception("pdf_processing_failed")

    if records_skipped > 0 and records_processed > 0:
        status = "completed_with_errors"
        error_message = f"{records_skipped} regulation(s) skipped"
    elif records_processed == 0:
        status = "failed"
        error_message = "No regulations were successfully processed"

    completed_at = datetime.now(UTC)

    session.add(
        IngestionLog(
            source=SOURCE_NAME,
            ingestion_type="full",
            started_at=started_at,
            completed_at=completed_at,
            records_processed=records_processed + records_skipped,
            records_added=records_added,
            records_updated=0,
            records_removed=0,
            status=status,
            error_message=error_message,
            source_vintage=started_at,
        )
    )
    await session.commit()

    result = IngestionResult(
        source=SOURCE_NAME,
        ingestion_type="full",
        started_at=started_at,
        completed_at=completed_at,
        records_processed=records_processed + records_skipped,
        records_added=records_added,
        records_updated=0,
        records_removed=0,
        records_skipped=records_skipped,
        status=status,
        error_message=error_message,
        source_vintage=started_at,
    )

    log.info(
        "ingestion_completed",
        status=status,
        records_processed=result.records_processed,
        records_added=records_added,
        records_skipped=records_skipped,
        duration_seconds=(completed_at - started_at).total_seconds(),
    )

    return result


async def _store_regulation_chunks(
    session: AsyncSession,
    chunks: list[ChunkResult],
    embeddings: list[list[float]],
    source_document: str,
    article_refs: dict[int, str | None],
) -> int:
    """Store regulation chunks with article_reference populated."""
    from datetime import UTC, datetime

    from sqlalchemy import delete, select

    from pipeline.db_models import DocumentChunk

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
                article_reference=article_refs.get(chunk.chunk_index),
                chunk_index=chunk.chunk_index,
                published_date=meta.published_date,
                ingestion_timestamp=now,
                data_vintage=meta.data_vintage,
                metadata_=None,
            )
        )

    await session.flush()

    logger.info(
        "regulation_chunks_stored",
        source_document=source_document,
        count=len(chunks),
    )

    return len(chunks)
