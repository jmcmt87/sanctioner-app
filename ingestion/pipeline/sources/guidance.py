from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline.chunk_store import store_document_chunks
from pipeline.chunking.text_chunker import ChunkMetadata, TextChunker
from pipeline.db_models import IngestionLog
from pipeline.embeddings import EmbeddingModel
from pipeline.extraction import extract_pdf
from pipeline.loaders import download_file
from pipeline.models import IngestionResult

logger = structlog.get_logger()

SOURCE_NAME = "guidance"

GUIDANCE_MANIFEST: dict[str, dict] = {
    "ofac_compliance_framework": {
        "url": "https://ofac.treasury.gov/media/16331/download",
        "title": "A Framework for OFAC Compliance Commitments",
        "published_date": date(2019, 5, 2),
    },
    "fifty_percent_rule": {
        "url": "https://ofac.treasury.gov/media/6051/download",
        "title": (
            "Revised Guidance on Entities Owned by Persons Whose Property"
            " and Interests in Property Are Blocked"
        ),
        "published_date": date(2014, 8, 13),
    },
}

MIN_EXTRACTION_QUALITY = 0.5


async def _process_pdf(
    slug: str,
    pdf_path: Path,
    manifest_entry: dict,
    session: AsyncSession,
    chunker: TextChunker,
    embedder: EmbeddingModel,
    data_vintage: datetime,
) -> int:
    """Extract, chunk, embed, and store a single guidance PDF. Returns chunk count."""
    log = logger.bind(slug=slug, path=str(pdf_path))

    doc = extract_pdf(pdf_path)
    log.info(
        "pdf_extracted",
        page_count=doc.page_count,
        extraction_quality=round(doc.extraction_quality, 3),
    )

    if doc.extraction_quality < MIN_EXTRACTION_QUALITY:
        log.warning(
            "skipping_low_quality_pdf",
            extraction_quality=round(doc.extraction_quality, 3),
        )
        return 0

    source_document = f"guidance/{slug}.pdf"
    metadata = ChunkMetadata(
        source_document=source_document,
        source_title=manifest_entry["title"],
        jurisdiction="US",
        document_type="guidance",
        published_date=manifest_entry["published_date"],
        data_vintage=data_vintage,
    )

    chunks = chunker.chunk_document(doc.text, metadata)
    if not chunks:
        log.warning("no_chunks_produced", slug=slug)
        return 0

    texts = [c.content for c in chunks]
    embeddings = embedder.embed_batch(texts)

    stored = await store_document_chunks(session, chunks, embeddings, source_document)
    log.info("pdf_stored", slug=slug, chunks_stored=stored)
    return stored


async def ingest_guidance_docs(
    session: AsyncSession,
    data_dir: Path,
) -> IngestionResult:
    """Ingest guidance documents from GUIDANCE_MANIFEST into the database."""
    started_at = datetime.now(UTC)
    data_vintage = started_at
    log = logger.bind(source=SOURCE_NAME)
    log.info("ingestion_started", manifest_size=len(GUIDANCE_MANIFEST))

    guidance_dir = data_dir / "guidance"
    guidance_dir.mkdir(parents=True, exist_ok=True)

    chunker = TextChunker()
    embedder = EmbeddingModel()

    records_processed = 0
    records_added = 0
    errors: list[str] = []

    for slug, entry in GUIDANCE_MANIFEST.items():
        pdf_path = guidance_dir / f"{slug}.pdf"

        try:
            if not pdf_path.exists():
                await download_file(entry["url"], pdf_path)

            chunks_stored = await _process_pdf(
                slug=slug,
                pdf_path=pdf_path,
                manifest_entry=entry,
                session=session,
                chunker=chunker,
                embedder=embedder,
                data_vintage=data_vintage,
            )
            records_processed += 1
            records_added += chunks_stored

        except Exception:
            records_processed += 1
            errors.append(slug)
            log.exception("pdf_processing_failed", slug=slug)

    if errors:
        status = "completed_with_errors"
        error_message = f"Failed PDFs: {', '.join(errors)}"
    else:
        status = "completed"
        error_message = None

    completed_at = datetime.now(UTC)

    session.add(
        IngestionLog(
            source=SOURCE_NAME,
            ingestion_type="full",
            started_at=started_at,
            completed_at=completed_at,
            records_processed=records_processed,
            records_added=records_added,
            records_updated=0,
            records_removed=0,
            status=status,
            error_message=error_message,
            source_vintage=data_vintage,
        )
    )
    await session.commit()

    result = IngestionResult(
        source=SOURCE_NAME,
        ingestion_type="full",
        started_at=started_at,
        completed_at=completed_at,
        records_processed=records_processed,
        records_added=records_added,
        records_updated=0,
        records_removed=0,
        records_skipped=0,
        status=status,
        error_message=error_message,
        source_vintage=data_vintage,
    )

    log.info(
        "ingestion_completed",
        status=status,
        records_processed=records_processed,
        records_added=records_added,
        errors=len(errors),
        duration_seconds=(completed_at - started_at).total_seconds(),
    )

    return result
