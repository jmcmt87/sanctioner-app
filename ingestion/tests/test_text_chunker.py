"""Unit tests for the text chunking module."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from pipeline.chunking.text_chunker import ChunkMetadata, TextChunker


def _make_metadata(**overrides: object) -> ChunkMetadata:
    defaults: dict[str, object] = {
        "source_document": "raw/enforcement/test/test.pdf",
        "source_title": "Test Document",
        "jurisdiction": "US",
        "document_type": "enforcement",
        "published_date": date(2024, 1, 15),
        "data_vintage": datetime(2026, 5, 16, tzinfo=UTC),
    }
    defaults.update(overrides)
    return ChunkMetadata(**defaults)


def _make_long_text(approx_chars: int = 5000) -> str:
    sentence = (
        "The Office of Foreign Assets Control administers and enforces "
        "economic sanctions programs primarily against countries and groups "
        "of individuals such as terrorists and narcotics traffickers. "
    )
    repetitions = approx_chars // len(sentence) + 1
    return (sentence * repetitions)[:approx_chars]


class TestChunkDocument:
    def test_chunks_long_text(self):
        chunker = TextChunker()
        metadata = _make_metadata()
        text = _make_long_text(5000)

        chunks = chunker.chunk_document(text, metadata)

        assert len(chunks) > 1

    def test_chunk_index_is_sequential(self):
        chunker = TextChunker(chunk_size=500, chunk_overlap=50)
        metadata = _make_metadata()
        text = _make_long_text(3000)

        chunks = chunker.chunk_document(text, metadata)

        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_metadata_propagated_to_all_chunks(self):
        chunker = TextChunker(chunk_size=500, chunk_overlap=50)
        metadata = _make_metadata()
        text = _make_long_text(3000)

        chunks = chunker.chunk_document(text, metadata)

        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.metadata == metadata

    def test_short_text_single_chunk(self):
        chunker = TextChunker()
        metadata = _make_metadata()
        text = (
            "This is a single chunk of text that is long enough to pass the minimum"
            " character threshold but short enough to fit into a single chunk without splitting."
        )

        chunks = chunker.chunk_document(text, metadata)

        assert len(chunks) == 1
        assert chunks[0].content == text
        assert chunks[0].chunk_index == 0

    def test_empty_text_returns_empty_list(self):
        chunker = TextChunker()
        metadata = _make_metadata()

        assert chunker.chunk_document("", metadata) == []

    def test_whitespace_only_returns_empty_list(self):
        chunker = TextChunker()
        metadata = _make_metadata()

        assert chunker.chunk_document("   \n  ", metadata) == []

    def test_chunks_have_overlap(self):
        chunker = TextChunker(chunk_size=500, chunk_overlap=100)
        metadata = _make_metadata()
        text = _make_long_text(3000)

        chunks = chunker.chunk_document(text, metadata)

        assert len(chunks) >= 3
        for i in range(len(chunks) - 1):
            tail = chunks[i].content[-80:]
            assert tail in chunks[i + 1].content, (
                f"Chunk {i} tail not found in chunk {i + 1} — overlap missing"
            )


class TestMetadataValidation:
    def test_invalid_jurisdiction_raises(self):
        chunker = TextChunker()
        metadata = _make_metadata(jurisdiction="XX")

        with pytest.raises(ValueError, match="Invalid jurisdiction"):
            chunker.chunk_document("some text", metadata)

    def test_invalid_document_type_raises(self):
        chunker = TextChunker()
        metadata = _make_metadata(document_type="unknown")

        with pytest.raises(ValueError, match="Invalid document_type"):
            chunker.chunk_document("some text", metadata)

    def test_valid_jurisdictions_accepted(self):
        chunker = TextChunker()
        text = (
            "This text is long enough to meet the minimum chunk length requirement"
            " for the chunker validation test across all valid jurisdictions."
        )

        for jurisdiction in ("US", "EU", "DE"):
            metadata = _make_metadata(jurisdiction=jurisdiction)
            chunks = chunker.chunk_document(text, metadata)
            assert len(chunks) == 1


class TestChunkQuality:
    def test_no_chunks_under_minimum_for_normal_text(self):
        chunker = TextChunker()
        metadata = _make_metadata()
        text = _make_long_text(5000)

        chunks = chunker.chunk_document(text, metadata)

        for chunk in chunks:
            assert len(chunk.content) >= 50, (
                f"Chunk {chunk.chunk_index} is only {len(chunk.content)} chars"
            )

    def test_custom_chunk_size(self):
        small_chunker = TextChunker(chunk_size=500, chunk_overlap=50)
        default_chunker = TextChunker()
        metadata = _make_metadata()
        text = _make_long_text(5000)

        small_chunks = small_chunker.chunk_document(text, metadata)
        default_chunks = default_chunker.chunk_document(text, metadata)

        assert len(small_chunks) > len(default_chunks)
