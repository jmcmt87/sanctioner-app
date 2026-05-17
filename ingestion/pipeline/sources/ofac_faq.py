from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline.chunk_store import store_document_chunks
from pipeline.chunking.text_chunker import ChunkMetadata, TextChunker
from pipeline.config import config
from pipeline.db_models import IngestionLog
from pipeline.embeddings import EmbeddingModel
from pipeline.extraction import extract_pdf
from pipeline.loaders import download_file
from pipeline.models import IngestionResult

logger = structlog.get_logger()

SOURCE_NAME = "ofac_faq"

OFAC_FAQ_MANIFEST: dict[str, dict] = {
    "guidance_ffi_sanctions": {
        "url": "https://ofac.treasury.gov/media/932436/download",
        "title": "OFAC Guidance for Foreign Financial Institutions on Sanctions",
        "published_date": date(2024, 4, 20),
    },
    "food_security_fact_sheet": {
        "url": "https://ofac.treasury.gov/media/931946/download",
        "title": "Humanitarian Assistance and Food Security Fact Sheet - Russia Sanctions",
        "published_date": date(2023, 3, 15),
    },
    "ofac_alert_russia_compliance": {
        "url": "https://ofac.treasury.gov/media/933656/download",
        "title": "OFAC Alert - Russia Sanctions Compliance Guidance",
        "published_date": date(2024, 6, 12),
    },
}

MIN_EXTRACTION_QUALITY = 0.5


async def ingest_ofac_faqs(
    session: AsyncSession,
    data_dir: Path,
) -> IngestionResult:
    """Ingest OFAC FAQ PDFs into the document_chunks table."""
    started_at = datetime.now(UTC)
    source_dir = data_dir / "ofac_faq"
    source_dir.mkdir(parents=True, exist_ok=True)

    log = logger.bind(source=SOURCE_NAME)
    log.info(
        "ingestion_started",
        data_dir=str(source_dir),
        manifest_count=len(OFAC_FAQ_MANIFEST),
    )

    chunker = TextChunker(chunk_size=1500, chunk_overlap=150)
    embedder = None if config.skip_embeddings else EmbeddingModel()

    records_processed = 0
    records_added = 0
    records_skipped = 0
    error_message: str | None = None
    status = "completed"

    for slug, entry in OFAC_FAQ_MANIFEST.items():
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
            source_document = f"ofac_faq/{slug}.pdf"
            metadata = ChunkMetadata(
                source_document=source_document,
                source_title=entry["title"],
                jurisdiction="US",
                document_type="faq",
                published_date=entry["published_date"],
                data_vintage=data_vintage,
            )
            chunks = chunker.chunk_document(extracted.text, metadata)

            if not chunks:
                pdf_log.warning("no_chunks_produced")
                records_skipped += 1
                continue

            embeddings = embedder.embed_batch([c.content for c in chunks]) if embedder else None

            stored = await store_document_chunks(session, chunks, embeddings, source_document)

            records_added += stored
            records_processed += 1
            pdf_log.info("pdf_ingested", chunks_stored=stored)

        except Exception:
            records_skipped += 1
            pdf_log.exception("pdf_processing_failed")

    if records_skipped > 0 and records_processed > 0:
        status = "completed_with_errors"
        error_message = f"{records_skipped} PDF(s) skipped due to errors or low quality"
    elif records_processed == 0:
        status = "failed"
        error_message = "No PDFs were successfully processed"

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
