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

SOURCE_NAME = "enforcement"

ENFORCEMENT_MANIFEST: dict[str, dict] = {
    "bnp_paribas_2014": {
        "url": "https://ofac.treasury.gov/media/13521/download",
        "title": "BNP Paribas Settlement Agreement",
        "published_date": date(2014, 6, 30),
    },
    "commerzbank_2015": {
        "url": "https://ofac.treasury.gov/media/12311/download",
        "title": "Commerzbank AG Settlement Agreement",
        "published_date": date(2015, 3, 12),
    },
    "unicredit_2019": {
        "url": "https://ofac.treasury.gov/media/15896/download",
        "title": "UniCredit Group Settlement Agreement",
        "published_date": date(2019, 4, 15),
    },
    "ing_2012": {
        "url": "https://ofac.treasury.gov/media/13891/download",
        "title": "ING Bank N.V. Settlement Agreement",
        "published_date": date(2012, 6, 12),
    },
    "hsbc_2012": {
        "url": "https://ofac.treasury.gov/media/13736/download",
        "title": "HSBC Holdings Settlement Agreement",
        "published_date": date(2012, 12, 11),
    },
    "standard_chartered_2019": {
        "url": "https://ofac.treasury.gov/media/15891/download",
        "title": "Standard Chartered Bank Settlement Agreement",
        "published_date": date(2019, 4, 9),
    },
    "clearstream_2014": {
        "url": "https://ofac.treasury.gov/media/13466/download",
        "title": "Clearstream Banking SA Settlement Agreement",
        "published_date": date(2014, 1, 23),
    },
    "deutsche_bank_2015": {
        "url": "https://ofac.treasury.gov/media/11631/download",
        "title": "Deutsche Bank AG Settlement Agreement",
        "published_date": date(2015, 11, 4),
    },
    "societe_generale_2018": {
        "url": "https://ofac.treasury.gov/media/15041/download",
        "title": "Societe Generale SA Settlement Agreement",
        "published_date": date(2018, 11, 19),
    },
    "credit_suisse_2009": {
        "url": "https://ofac.treasury.gov/media/12676/download",
        "title": "Credit Suisse AG Settlement Agreement",
        "published_date": date(2009, 12, 16),
    },
    "jp_morgan_2011": {
        "url": "https://ofac.treasury.gov/media/13886/download",
        "title": "JPMorgan Chase Bank Settlement Agreement",
        "published_date": date(2011, 8, 25),
    },
    "barclays_2010": {
        "url": "https://ofac.treasury.gov/system/files/126/08182010.pdf",
        "title": "Barclays Bank PLC Settlement Agreement",
        "published_date": date(2010, 8, 18),
    },
    "paypal_2015": {
        "url": "https://ofac.treasury.gov/media/12326/download",
        "title": "PayPal Inc. Settlement Agreement",
        "published_date": date(2015, 3, 25),
    },
    "zhongxing_2017": {
        "url": "https://home.treasury.gov/system/files/126/20170307_zte_settlement.pdf",
        "title": "Zhongxing Telecommunications Settlement Agreement",
        "published_date": date(2017, 3, 7),
    },
    "epsilon_electronics_2018": {
        "url": "https://ofac.treasury.gov/media/13546/download",
        "title": "Epsilon Electronics Inc. Settlement Agreement",
        "published_date": date(2018, 9, 13),
    },
    "exxonmobil_2017": {
        "url": "https://ofac.treasury.gov/media/12956/download",
        "title": "ExxonMobil Settlement Agreement",
        "published_date": date(2017, 7, 20),
    },
    "general_electric_2019": {
        "url": "https://ofac.treasury.gov/media/26481/download",
        "title": "General Electric Settlement Agreement",
        "published_date": date(2019, 10, 1),
    },
    "bitgo_2020": {
        "url": "https://ofac.treasury.gov/media/50266/download",
        "title": "BitGo Inc. Settlement Agreement",
        "published_date": date(2020, 12, 30),
    },
    "bittrex_2022": {
        "url": "https://ofac.treasury.gov/media/932351/download",
        "title": "Bittrex Inc. Settlement Agreement",
        "published_date": date(2022, 10, 11),
    },
    "apollo_aviation_2019": {
        "url": "https://ofac.treasury.gov/media/13176/download",
        "title": "Apollo Aviation Group Settlement Agreement",
        "published_date": date(2019, 11, 7),
    },
}


async def ingest_enforcement_pdfs(
    session: AsyncSession,
    data_dir: Path,
) -> IngestionResult:
    """Ingest OFAC enforcement action PDFs into the document_chunks table."""
    started_at = datetime.now(UTC)
    source_dir = data_dir / "enforcement"

    log = logger.bind(source=SOURCE_NAME)
    log.info(
        "ingestion_started", data_dir=str(source_dir), manifest_count=len(ENFORCEMENT_MANIFEST)
    )

    chunker = TextChunker()
    embedder = EmbeddingModel()

    records_processed = 0
    records_added = 0
    records_skipped = 0
    error_message: str | None = None
    status = "completed"

    for slug, entry in ENFORCEMENT_MANIFEST.items():
        pdf_path = source_dir / f"{slug}.pdf"
        pdf_log = log.bind(slug=slug, path=str(pdf_path))

        try:
            # Download phase
            if pdf_path.exists():
                pdf_log.info("pdf_already_exists_skipping_download")
            else:
                await download_file(entry["url"], pdf_path)
                pdf_log.info("pdf_downloaded")

            # Extract text
            extracted = await extract_pdf(pdf_path)

            if extracted.extraction_quality < 0.5:
                pdf_log.warning(
                    "low_extraction_quality_skipping",
                    extraction_quality=round(extracted.extraction_quality, 3),
                )
                records_skipped += 1
                continue

            # Chunk
            data_vintage = datetime.now(UTC)
            metadata = ChunkMetadata(
                source_document=f"enforcement/{slug}.pdf",
                source_title=entry["title"],
                jurisdiction="US",
                document_type="enforcement",
                published_date=entry["published_date"],
                data_vintage=data_vintage,
            )
            chunks = chunker.chunk_document(extracted.text, metadata)

            if not chunks:
                pdf_log.warning("no_chunks_produced")
                records_skipped += 1
                continue

            # Embed
            embeddings = embedder.embed_batch([c.content for c in chunks])

            # Store
            stored = await store_document_chunks(
                session, chunks, embeddings, f"enforcement/{slug}.pdf"
            )

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
