from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.extraction import ExtractedDocument
from pipeline.sources.guidance import (
    GUIDANCE_MANIFEST,
    SOURCE_NAME,
    ingest_guidance_docs,
)


class TestGuidanceManifest:
    def test_manifest_has_at_least_two_entries(self):
        assert len(GUIDANCE_MANIFEST) >= 2

    def test_each_entry_has_required_keys(self):
        for slug, entry in GUIDANCE_MANIFEST.items():
            assert "url" in entry, f"{slug} missing 'url'"
            assert "title" in entry, f"{slug} missing 'title'"
            assert "published_date" in entry, f"{slug} missing 'published_date'"

    def test_published_dates_are_date_objects(self):
        for slug, entry in GUIDANCE_MANIFEST.items():
            assert isinstance(entry["published_date"], date), f"{slug} has non-date published_date"

    def test_ofac_compliance_framework_present(self):
        assert "ofac_compliance_framework" in GUIDANCE_MANIFEST

    def test_fifty_percent_rule_present(self):
        assert "fifty_percent_rule" in GUIDANCE_MANIFEST

    def test_source_name(self):
        assert SOURCE_NAME == "guidance"


class TestIngestGuidanceDocs:
    @pytest.fixture()
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.fixture()
    def _mock_download(self):
        with patch(
            "pipeline.sources.guidance.download_file",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = b"%PDF-fake-content"
            yield mock

    @pytest.fixture()
    def _mock_extract(self):
        with patch("pipeline.sources.guidance.extract_pdf") as mock:
            mock.return_value = ExtractedDocument(
                text="This is guidance document content for testing purposes.",
                page_count=5,
                ocr_pages=[],
                extraction_quality=0.95,
            )
            yield mock

    @pytest.fixture()
    def _mock_embedder(self):
        with patch("pipeline.sources.guidance.EmbeddingModel") as mock_cls:
            instance = MagicMock()
            instance.embed_batch.return_value = [[0.1] * 1024]
            mock_cls.return_value = instance
            yield mock_cls

    @pytest.fixture()
    def _mock_store(self):
        with patch(
            "pipeline.sources.guidance.store_document_chunks",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = 3
            yield mock

    @pytest.fixture()
    def _all_mocks(self, _mock_download, _mock_extract, _mock_embedder, _mock_store):
        """Activate all mocks together."""

    @pytest.mark.usefixtures("_all_mocks")
    async def test_returns_completed_status(self, mock_session, tmp_path):
        result = await ingest_guidance_docs(mock_session, tmp_path)

        assert result.status == "completed"

    @pytest.mark.usefixtures("_all_mocks")
    async def test_returns_correct_source_name(self, mock_session, tmp_path):
        result = await ingest_guidance_docs(mock_session, tmp_path)

        assert result.source == "guidance"

    @pytest.mark.usefixtures("_all_mocks")
    async def test_records_processed_matches_manifest_size(self, mock_session, tmp_path):
        result = await ingest_guidance_docs(mock_session, tmp_path)

        assert result.records_processed == len(GUIDANCE_MANIFEST)

    @pytest.mark.usefixtures("_all_mocks")
    async def test_records_added_reflects_stored_chunks(self, mock_session, tmp_path):
        result = await ingest_guidance_docs(mock_session, tmp_path)

        assert result.records_added == 3 * len(GUIDANCE_MANIFEST)

    @pytest.mark.usefixtures("_all_mocks")
    async def test_creates_ingestion_log(self, mock_session, tmp_path):
        await ingest_guidance_docs(mock_session, tmp_path)

        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited_once()

    @pytest.mark.usefixtures("_all_mocks")
    async def test_ingestion_type_is_full(self, mock_session, tmp_path):
        result = await ingest_guidance_docs(mock_session, tmp_path)

        assert result.ingestion_type == "full"

    @pytest.mark.usefixtures("_all_mocks")
    async def test_tags_with_guidance_document_type(self, _mock_store, mock_session, tmp_path):
        await ingest_guidance_docs(mock_session, tmp_path)

        for call in _mock_store.call_args_list:
            chunks = call.args[1] if len(call.args) > 1 else call.kwargs["chunks"]
            for chunk in chunks:
                assert chunk.metadata.document_type == "guidance"

    @pytest.mark.usefixtures("_all_mocks")
    async def test_tags_with_us_jurisdiction(self, _mock_store, mock_session, tmp_path):
        await ingest_guidance_docs(mock_session, tmp_path)

        for call in _mock_store.call_args_list:
            chunks = call.args[1] if len(call.args) > 1 else call.kwargs["chunks"]
            for chunk in chunks:
                assert chunk.metadata.jurisdiction == "US"

    @pytest.mark.usefixtures("_mock_extract", "_mock_embedder", "_mock_store")
    async def test_skips_download_when_file_exists(self, _mock_download, mock_session, tmp_path):
        guidance_dir = tmp_path / "guidance"
        guidance_dir.mkdir()
        for slug in GUIDANCE_MANIFEST:
            (guidance_dir / f"{slug}.pdf").write_bytes(b"%PDF-exists")

        await ingest_guidance_docs(mock_session, tmp_path)

        _mock_download.assert_not_awaited()

    @pytest.mark.usefixtures("_mock_embedder", "_mock_store")
    async def test_handles_per_pdf_failure_gracefully(
        self, _mock_download, _mock_extract, mock_session, tmp_path
    ):
        _mock_extract.side_effect = RuntimeError("extraction failed")

        result = await ingest_guidance_docs(mock_session, tmp_path)

        assert result.status == "completed_with_errors"
        assert result.records_processed == len(GUIDANCE_MANIFEST)
        assert result.error_message is not None
