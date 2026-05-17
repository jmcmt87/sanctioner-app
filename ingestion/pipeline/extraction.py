"""PDF text extraction with OCR fallback for scanned pages.

Uses PyMuPDF for native text extraction and Tesseract OCR as a fallback
when pages contain images instead of selectable text (common in enforcement
action PDFs and older regulatory guidance documents).
"""

from __future__ import annotations

import asyncio
import io
import re
import string
from pathlib import Path

import fitz
import pytesseract
import structlog
from PIL import Image
from pydantic import BaseModel

logger = structlog.get_logger()

PRINTABLE_CHARS = set(string.ascii_letters + string.digits + string.punctuation + string.whitespace)

MIN_TEXT_LENGTH_FOR_NATIVE = 100
MIN_PAGE_QUALITY_FOR_NATIVE = 0.5


class ExtractedDocument(BaseModel):
    text: str
    page_count: int
    ocr_pages: list[int]
    extraction_quality: float


def _extract_pdf_sync(path: Path) -> ExtractedDocument:
    """Extract text from a PDF, falling back to OCR for scanned pages."""
    if not path.exists():
        msg = f"PDF file not found: {path}"
        raise FileNotFoundError(msg)

    doc = fitz.open(str(path))
    page_count = len(doc)
    log = logger.bind(path=str(path), page_count=page_count)
    log.info("pdf_extraction_started")

    page_texts: list[str] = []
    ocr_pages: list[int] = []

    for page_num in range(page_count):
        page = doc[page_num]
        text = page.get_text("text")

        needs_ocr = False
        if len(text.strip()) < MIN_TEXT_LENGTH_FOR_NATIVE:
            needs_ocr = _page_has_content(page)
        elif _calculate_quality(text) < MIN_PAGE_QUALITY_FOR_NATIVE:
            needs_ocr = True
            log.info("garbled_text_detected", page=page_num)

        if needs_ocr:
            log.info("ocr_fallback", page=page_num)
            text = _ocr_page(page)
            ocr_pages.append(page_num)

        cleaned = _clean_page_text(text, page_num, page_count)
        page_texts.append(cleaned)

    doc.close()

    full_text = "\n\n".join(page_texts)
    quality = _calculate_quality(full_text)

    log.info(
        "pdf_extraction_completed",
        extraction_quality=round(quality, 3),
        ocr_page_count=len(ocr_pages),
    )
    if quality < 0.7:
        log.warning("low_extraction_quality", extraction_quality=round(quality, 3))

    return ExtractedDocument(
        text=full_text,
        page_count=page_count,
        ocr_pages=ocr_pages,
        extraction_quality=quality,
    )


def _page_has_content(page: fitz.Page) -> bool:
    """Check if a page has visible content (images or drawings), not just blank."""
    return len(page.get_images()) > 0 or len(page.get_drawings()) > 0


def _ocr_page(page: fitz.Page) -> str:
    """Render a page to an image and run Tesseract OCR."""
    pixmap = page.get_pixmap(dpi=300)
    img_bytes = pixmap.tobytes("png")
    image = Image.open(io.BytesIO(img_bytes))
    return pytesseract.image_to_string(image)


def _normalize_text(text: str) -> str:
    """Normalize common PDF extraction artifacts."""
    text = text.replace(" ", " ")
    text = text.replace("‑", "-")
    text = text.replace("–", "-")
    text = text.replace("—", "--")
    text = text.replace("‘", "'")
    text = text.replace("’", "'")
    text = text.replace("“", '"')
    text = text.replace("”", '"')
    return text


def _clean_page_text(text: str, page_num: int, total_pages: int) -> str:
    """Remove PDF artifacts: standalone page numbers and excessive whitespace."""
    text = _normalize_text(text)

    lines = text.split("\n")
    cleaned_lines: list[str] = []

    display_page = page_num + 1
    page_number_pattern = re.compile(r"^\s*" + re.escape(str(display_page)) + r"\s*$")

    for line in lines:
        if page_number_pattern.match(line):
            continue
        cleaned_lines.append(line)

    result = "\n".join(cleaned_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _calculate_quality(text: str) -> float:
    """Ratio of printable ASCII characters to total characters."""
    if not text:
        return 0.0
    printable_count = sum(1 for c in text if c in PRINTABLE_CHARS)
    return printable_count / len(text)


async def extract_pdf(path: Path) -> ExtractedDocument:
    """Async wrapper around PDF extraction — offloads blocking I/O to a thread."""
    return await asyncio.to_thread(_extract_pdf_sync, path)
