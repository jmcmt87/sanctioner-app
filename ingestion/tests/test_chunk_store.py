from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from pipeline.chunk_store import store_document_chunks
from pipeline.chunking.text_chunker import ChunkMetadata, ChunkResult


def _make_metadata(**overrides: object) -> ChunkMetadata:
    defaults: dict[str, object] = {
        "source_document": "raw/enforcement/test/doc.pdf",
        "source_title": "Test Enforcement Action",
        "jurisdiction": "US",
        "document_type": "enforcement",
        "published_date": date(2024, 1, 15),
        "data_vintage": datetime(2026, 5, 16, tzinfo=UTC),
    }
    defaults.update(overrides)
    return ChunkMetadata(**defaults)


def _make_chunks(count: int = 3) -> list[ChunkResult]:
    meta = _make_metadata()
    return [
        ChunkResult(content=f"Chunk content number {i}", chunk_index=i, metadata=meta)
        for i in range(count)
    ]


def _make_embeddings(count: int = 3, dim: int = 1024) -> list[list[float]]:
    return [[0.1] * dim for _ in range(count)]


def _make_mock_session() -> AsyncMock:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    session.execute.return_value = mock_result
    session.add = MagicMock()
    return session


class TestStoreDocumentChunks:
    async def test_stores_correct_number_of_chunks(self):
        session = _make_mock_session()
        chunks = _make_chunks(3)
        embeddings = _make_embeddings(3)

        count = await store_document_chunks(
            session, chunks, embeddings, "raw/enforcement/test/doc.pdf"
        )

        assert count == 3
        assert session.add.call_count == 3

    async def test_mismatched_chunks_and_embeddings_raises(self):
        session = _make_mock_session()
        chunks = _make_chunks(3)
        embeddings = _make_embeddings(2)

        with pytest.raises(ValueError, match="must have equal length"):
            await store_document_chunks(session, chunks, embeddings, "raw/enforcement/test/doc.pdf")

    async def test_deletes_existing_chunks_before_insert(self):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [MagicMock(), MagicMock()]
        session.execute.return_value = mock_result
        session.add = MagicMock()

        chunks = _make_chunks(1)
        embeddings = _make_embeddings(1)

        await store_document_chunks(session, chunks, embeddings, "raw/enforcement/test/doc.pdf")

        assert session.execute.call_count >= 2

    async def test_empty_chunks_stores_nothing(self):
        session = _make_mock_session()

        count = await store_document_chunks(session, [], [], "raw/enforcement/test/doc.pdf")

        assert count == 0
        assert session.add.call_count == 0

    async def test_flushes_session_after_adding(self):
        session = _make_mock_session()
        chunks = _make_chunks(2)
        embeddings = _make_embeddings(2)

        await store_document_chunks(session, chunks, embeddings, "raw/enforcement/test/doc.pdf")

        session.flush.assert_awaited_once()
