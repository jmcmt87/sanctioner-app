"""Tests for the enforcement PDF source parser.

Tests manifest integrity and the ingest_enforcement_pdfs function with mocked
I/O (downloads, PDF extraction, embedding, chunk storage).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.models import IngestionResult
from pipeline.sources.enforcement import (
    ENFORCEMENT_MANIFEST,
    SOURCE_NAME,
    ingest_enforcement_pdfs,
)

REQUIRED_MANIFEST_KEYS = {"url", "title", "published_date"}


# ── Manifest validation ────────────────────────────────────────────────────


class TestEnforcementManifest:
    def test_manifest_is_not_empty(self):
        assert len(ENFORCEMENT_MANIFEST) > 0

    def test_every_entry_has_required_keys(self):
        for slug, entry in ENFORCEMENT_MANIFEST.items():
            missing = REQUIRED_MANIFEST_KEYS - set(entry.keys())
            assert not missing, f"{slug} is missing keys: {missing}"

    def test_every_url_is_https(self):
        for slug, entry in ENFORCEMENT_MANIFEST.items():
            assert entry["url"].startswith("https://"), f"{slug} URL is not HTTPS"

    def test_every_title_is_non_empty_string(self):
        for slug, entry in ENFORCEMENT_MANIFEST.items():
            assert isinstance(entry["title"], str) and entry["title"], (
                f"{slug} has empty or non-string title"
            )

    def test_every_published_date_is_date(self):
        for slug, entry in ENFORCEMENT_MANIFEST.items():
            assert isinstance(entry["published_date"], date), f"{slug} published_date is not a date"

    def test_slugs_are_unique(self):
        slugs = list(ENFORCEMENT_MANIFEST.keys())
        assert len(slugs) == len(set(slugs))

    def test_source_name(self):
        assert SOURCE_NAME == "enforcement"


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_extracted_document(quality: float = 0.95):
    """Create a mock ExtractedDocument with configurable quality."""
    doc = MagicMock()
    doc.text = "This is a test enforcement action document with enough content to chunk."
    doc.page_count = 5
    doc.ocr_pages = []
    doc.extraction_quality = quality
    return doc


def _make_chunk_result():
    """Create a mock ChunkResult."""
    chunk = MagicMock()
    chunk.content = "Test chunk content for embedding."
    chunk.chunk_index = 0
    chunk.metadata = MagicMock()
    return chunk


def _make_mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    return session


_SMALL_MANIFEST = {
    "test_doc_a": {
        "url": "https://example.com/a.pdf",
        "title": "Test Document A",
        "published_date": date(2020, 1, 1),
    },
    "test_doc_b": {
        "url": "https://example.com/b.pdf",
        "title": "Test Document B",
        "published_date": date(2021, 6, 15),
    },
}


def _write_fake_pdf(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-1.4 fake content")


# ── Integration tests ──────────────────────────────────────────────────────


class TestIngestEnforcementPdfs:
    """Tests for the main ingest_enforcement_pdfs function with mocked dependencies."""

    @pytest.fixture()
    def mock_deps(self):
        """Patch all external dependencies used by ingest_enforcement_pdfs."""
        with (
            patch(
                "pipeline.sources.enforcement.ENFORCEMENT_MANIFEST",
                _SMALL_MANIFEST,
            ),
            patch(
                "pipeline.sources.enforcement.download_file",
                new_callable=AsyncMock,
            ) as mock_download,
            patch(
                "pipeline.sources.enforcement.extract_pdf",
                new_callable=AsyncMock,
            ) as mock_extract,
            patch(
                "pipeline.sources.enforcement.EmbeddingModel",
            ) as mock_embedder_cls,
            patch(
                "pipeline.sources.enforcement.store_document_chunks",
                new_callable=AsyncMock,
            ) as mock_store,
        ):

            async def _fake_download(url: str, dest: Path) -> None:
                _write_fake_pdf(dest)

            mock_download.side_effect = _fake_download
            mock_extract.return_value = _make_extracted_document(quality=0.95)

            mock_embedder = MagicMock()
            mock_embedder.embed_batch.return_value = [[0.1] * 1024]
            mock_embedder_cls.return_value = mock_embedder

            mock_chunker_chunks = [_make_chunk_result()]
            with patch(
                "pipeline.sources.enforcement.TextChunker",
            ) as mock_chunker_cls:
                mock_chunker = MagicMock()
                mock_chunker.chunk_document.return_value = mock_chunker_chunks
                mock_chunker_cls.return_value = mock_chunker

                mock_store.return_value = 5

                yield {
                    "download": mock_download,
                    "extract": mock_extract,
                    "embedder_cls": mock_embedder_cls,
                    "embedder": mock_embedder,
                    "store": mock_store,
                    "chunker_cls": mock_chunker_cls,
                    "chunker": mock_chunker,
                }

    async def test_returns_ingestion_result(self, mock_deps, tmp_path: Path):
        session = _make_mock_session()
        result = await ingest_enforcement_pdfs(session, tmp_path)
        assert isinstance(result, IngestionResult)

    async def test_completed_status_on_success(self, mock_deps, tmp_path: Path):
        session = _make_mock_session()
        result = await ingest_enforcement_pdfs(session, tmp_path)
        assert result.status == "completed"
        assert result.error_message is None

    async def test_records_processed_matches_manifest_size(self, mock_deps, tmp_path: Path):
        session = _make_mock_session()
        result = await ingest_enforcement_pdfs(session, tmp_path)
        assert result.records_processed == len(_SMALL_MANIFEST)

    async def test_records_added_reflects_stored_chunks(self, mock_deps, tmp_path: Path):
        session = _make_mock_session()
        result = await ingest_enforcement_pdfs(session, tmp_path)
        assert result.records_added == 5 * len(_SMALL_MANIFEST)

    async def test_source_is_enforcement(self, mock_deps, tmp_path: Path):
        session = _make_mock_session()
        result = await ingest_enforcement_pdfs(session, tmp_path)
        assert result.source == "enforcement"

    async def test_ingestion_type_is_full(self, mock_deps, tmp_path: Path):
        session = _make_mock_session()
        result = await ingest_enforcement_pdfs(session, tmp_path)
        assert result.ingestion_type == "full"

    async def test_creates_ingestion_log(self, mock_deps, tmp_path: Path):
        session = _make_mock_session()
        await ingest_enforcement_pdfs(session, tmp_path)
        session.add.assert_called_once()
        session.commit.assert_awaited_once()

    async def test_downloads_missing_pdfs(self, mock_deps, tmp_path: Path):
        session = _make_mock_session()
        await ingest_enforcement_pdfs(session, tmp_path)
        assert mock_deps["download"].await_count == len(_SMALL_MANIFEST)

    async def test_skips_download_for_existing_files(self, mock_deps, tmp_path: Path):
        enforcement_dir = tmp_path / "enforcement"
        enforcement_dir.mkdir()
        for slug in _SMALL_MANIFEST:
            (enforcement_dir / f"{slug}.pdf").write_bytes(b"fake pdf")

        session = _make_mock_session()
        await ingest_enforcement_pdfs(session, tmp_path)
        mock_deps["download"].assert_not_awaited()

    async def test_creates_chunker_and_embedder_once(self, mock_deps, tmp_path: Path):
        session = _make_mock_session()
        await ingest_enforcement_pdfs(session, tmp_path)
        mock_deps["chunker_cls"].assert_called_once()
        mock_deps["embedder_cls"].assert_called_once()

    async def test_low_quality_extraction_skips_pdf(self, mock_deps, tmp_path: Path):
        mock_deps["extract"].return_value = _make_extracted_document(quality=0.3)

        session = _make_mock_session()
        result = await ingest_enforcement_pdfs(session, tmp_path)

        assert result.records_skipped == len(_SMALL_MANIFEST)
        assert result.records_added == 0
        mock_deps["store"].assert_not_awaited()

    async def test_download_failure_skips_pdf_but_continues(self, mock_deps, tmp_path: Path):
        call_count = 0

        async def _fail_first(url, dest, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("download failed")
            _write_fake_pdf(dest)

        mock_deps["download"].side_effect = _fail_first

        session = _make_mock_session()
        result = await ingest_enforcement_pdfs(session, tmp_path)

        assert result.records_skipped == 1
        assert result.records_processed == len(_SMALL_MANIFEST)
        assert result.status == "completed_with_errors"

    async def test_all_failures_produces_failed_status(self, mock_deps, tmp_path: Path):
        mock_deps["download"].side_effect = RuntimeError("network error")

        session = _make_mock_session()
        result = await ingest_enforcement_pdfs(session, tmp_path)

        assert result.status == "failed"
        assert result.records_skipped == len(_SMALL_MANIFEST)
        assert result.records_processed == len(_SMALL_MANIFEST)

    async def test_extraction_failure_skips_and_continues(self, mock_deps, tmp_path: Path):
        call_count = 0
        original_return = mock_deps["extract"].return_value

        def _fail_first(path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("extraction failed")
            return original_return

        mock_deps["extract"].side_effect = _fail_first

        session = _make_mock_session()
        result = await ingest_enforcement_pdfs(session, tmp_path)

        assert result.records_skipped == 1
        assert result.records_processed == len(_SMALL_MANIFEST)
