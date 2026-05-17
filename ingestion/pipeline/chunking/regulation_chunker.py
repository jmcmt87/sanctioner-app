"""Structure-aware chunker for EU regulation texts.

Splits regulation documents at article boundaries and preserves article_reference
metadata for each chunk. Articles are never split across chunks unless they exceed
the max chunk size, in which case they're split at paragraph boundaries.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

ARTICLE_PATTERN = re.compile(
    r"^(Article\s+\d+[a-z]*)\b",
    re.MULTILINE,
)

PARAGRAPH_PATTERN = re.compile(r"^\d+\.\s+", re.MULTILINE)

DEFAULT_MAX_CHUNK = 2500
DEFAULT_MIN_CHUNK = 100


class RegulationChunkMetadata(BaseModel):
    source_document: str
    source_title: str
    jurisdiction: str
    document_type: str
    published_date: date | None
    data_vintage: datetime
    article_reference: str | None = None


class RegulationChunkResult(BaseModel):
    content: str
    chunk_index: int
    metadata: RegulationChunkMetadata


class RegulationChunker:
    def __init__(
        self,
        max_chunk_size: int = DEFAULT_MAX_CHUNK,
        min_chunk_size: int = DEFAULT_MIN_CHUNK,
    ) -> None:
        self._max_chunk_size = max_chunk_size
        self._min_chunk_size = min_chunk_size

    def chunk_regulation(
        self,
        text: str,
        source_document: str,
        source_title: str,
        jurisdiction: str,
        published_date: date | None,
        data_vintage: datetime,
    ) -> list[RegulationChunkResult]:
        """Split regulation text into chunks at article boundaries."""
        if not text or not text.strip():
            return []

        articles = self._split_into_articles(text)
        chunks: list[RegulationChunkResult] = []
        idx = 0

        for article_ref, article_text in articles:
            if len(article_text) < self._min_chunk_size:
                logger.info(
                    "runt_article_filtered",
                    source=source_document,
                    article=article_ref,
                    length=len(article_text),
                )
                continue

            metadata = RegulationChunkMetadata(
                source_document=source_document,
                source_title=source_title,
                jurisdiction=jurisdiction,
                document_type="regulation",
                published_date=published_date,
                data_vintage=data_vintage,
                article_reference=article_ref,
            )

            if len(article_text) <= self._max_chunk_size:
                chunks.append(
                    RegulationChunkResult(content=article_text, chunk_index=idx, metadata=metadata)
                )
                idx += 1
            else:
                sub_chunks = self._split_article(article_text)
                for sub in sub_chunks:
                    if len(sub) < self._min_chunk_size:
                        continue
                    chunks.append(
                        RegulationChunkResult(content=sub, chunk_index=idx, metadata=metadata)
                    )
                    idx += 1

        logger.info(
            "regulation_chunked",
            source=source_document,
            articles_found=len(articles),
            chunks_produced=len(chunks),
        )

        return chunks

    def _split_into_articles(self, text: str) -> list[tuple[str | None, str]]:
        """Split text into (article_reference, article_text) pairs."""
        matches = list(ARTICLE_PATTERN.finditer(text))

        if not matches:
            return [(None, text)]

        articles: list[tuple[str | None, str]] = []

        # Preamble before first article
        if matches[0].start() > 0:
            preamble = text[: matches[0].start()].strip()
            if preamble:
                articles.append((None, preamble))

        for i, match in enumerate(matches):
            article_ref = match.group(1)
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            article_text = text[start:end].strip()
            articles.append((article_ref, article_text))

        return articles

    def _split_article(self, text: str) -> list[str]:
        """Split a long article at paragraph boundaries."""
        paragraphs = PARAGRAPH_PATTERN.split(text)
        numbers = PARAGRAPH_PATTERN.findall(text)

        if len(paragraphs) <= 1:
            return self._hard_split(text)

        # Reconstruct paragraphs with their numbers
        result_parts: list[str] = []
        if paragraphs[0].strip():
            result_parts.append(paragraphs[0].strip())

        for i, para in enumerate(paragraphs[1:]):
            if para.strip():
                result_parts.append(f"{numbers[i]}{para.strip()}")

        # Merge small paragraphs into chunks up to max_chunk_size
        chunks: list[str] = []
        current = ""
        for part in result_parts:
            if current and len(current) + len(part) + 1 > self._max_chunk_size:
                chunks.append(current)
                current = part
            else:
                current = f"{current}\n{part}" if current else part

        if current:
            chunks.append(current)

        return chunks

    def _hard_split(self, text: str) -> list[str]:
        """Last resort: split at sentence boundaries when paragraphs aren't available."""
        sentences = re.split(r"(?<=\.)\s+", text)
        chunks: list[str] = []
        current = ""

        for sentence in sentences:
            if current and len(current) + len(sentence) + 1 > self._max_chunk_size:
                chunks.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}" if current else sentence

        if current:
            chunks.append(current)

        return chunks
