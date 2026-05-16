"""Tests for PDF text extraction with OCR fallback.

Uses PyMuPDF to create minimal test PDFs in-memory.
OCR tests mock pytesseract to avoid requiring Tesseract installation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz

from pipeline.extraction import (
    ExtractedDocument,
    _calculate_quality,
    _clean_page_text,
    extract_pdf,
)


def _create_test_pdf(path: Path, pages: list[str]) -> Path:
    """Create a minimal PDF with the given text on each page."""
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text, fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


class TestExtractPdf:
    def test_extracts_text_from_single_page_pdf(self, tmp_path: Path):
        content = "This is a test document with enough text to pass the threshold. " * 5
        pdf_path = _create_test_pdf(tmp_path / "single.pdf", [content])

        result = extract_pdf(pdf_path)

        assert isinstance(result, ExtractedDocument)
        assert "This is a test document" in result.text

    def test_extracts_text_from_multi_page_pdf(self, tmp_path: Path):
        pages = [
            "First page content that is long enough to exceed the minimum threshold easily. " * 3,
            "Second page content that is also long enough to exceed the threshold minimum. " * 3,
            "Third page content with sufficient length to avoid triggering OCR fallback. " * 3,
        ]
        pdf_path = _create_test_pdf(tmp_path / "multi.pdf", pages)

        result = extract_pdf(pdf_path)

        assert "First page content" in result.text
        assert "Second page content" in result.text
        assert "Third page content" in result.text

    def test_returns_correct_page_count(self, tmp_path: Path):
        pages = ["Page one. " * 20, "Page two. " * 20, "Page three. " * 20]
        pdf_path = _create_test_pdf(tmp_path / "count.pdf", pages)

        result = extract_pdf(pdf_path)

        assert result.page_count == 3

    def test_empty_pdf_returns_empty_text(self, tmp_path: Path):
        pdf_path = _create_test_pdf(tmp_path / "empty.pdf", ["", ""])

        result = extract_pdf(pdf_path)

        assert result.text.strip() == ""
        assert result.page_count == 2

    def test_file_not_found_raises(self, tmp_path: Path):
        nonexistent = tmp_path / "does_not_exist.pdf"

        try:
            extract_pdf(nonexistent)
            raise AssertionError("Expected FileNotFoundError")  # noqa: TRY301
        except FileNotFoundError:
            pass


class TestCleanPageText:
    def test_removes_standalone_page_numbers(self):
        text = "Some content\n5\nMore content"
        result = _clean_page_text(text, page_num=4, total_pages=10)

        assert "\n5\n" not in result
        assert "Some content" in result
        assert "More content" in result

    def test_preserves_page_numbers_in_text(self):
        text = "See page 5 of the report for details"
        result = _clean_page_text(text, page_num=4, total_pages=10)

        assert "page 5 of the report" in result

    def test_collapses_excessive_whitespace(self):
        text = "First paragraph\n\n\n\n\nSecond paragraph"
        result = _clean_page_text(text, page_num=0, total_pages=1)

        assert "\n\n\n" not in result
        assert "First paragraph" in result
        assert "Second paragraph" in result


class TestCalculateQuality:
    def test_pure_ascii_text_returns_high_quality(self):
        text = "This is normal English text with numbers 123 and punctuation."
        quality = _calculate_quality(text)

        assert quality > 0.95

    def test_garbled_text_returns_low_quality(self):
        text = "\x00\x01\x02\x03\x04\x05\x06\x07" * 20
        quality = _calculate_quality(text)

        assert quality < 0.7

    def test_empty_text_returns_zero(self):
        assert _calculate_quality("") == 0.0


class TestOcrPage:
    @patch("pipeline.extraction.pytesseract")
    def test_ocr_fallback_called_for_short_text(self, mock_tesseract: MagicMock, tmp_path: Path):
        """When native extraction yields < 100 chars on a page with images, OCR runs."""
        mock_tesseract.image_to_string.return_value = "OCR extracted text " * 10

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Short", fontsize=12)

        img_doc = fitz.open()
        img_page = img_doc.new_page(width=100, height=100)
        pix = img_page.get_pixmap()
        img_bytes = pix.tobytes("png")
        img_doc.close()

        page.insert_image(fitz.Rect(0, 0, 100, 100), stream=img_bytes)

        pdf_path = tmp_path / "scanned.pdf"
        doc.save(str(pdf_path))
        doc.close()

        result = extract_pdf(pdf_path)

        mock_tesseract.image_to_string.assert_called_once()
        assert "OCR extracted text" in result.text

    @patch("pipeline.extraction.pytesseract")
    def test_ocr_pages_tracked(self, mock_tesseract: MagicMock, tmp_path: Path):
        """The ocr_pages list records which page indices used OCR."""
        mock_tesseract.image_to_string.return_value = "Fallback OCR content " * 10

        doc = fitz.open()

        page0 = doc.new_page()
        long_text = "Normal text content that exceeds the minimum threshold. " * 5
        page0.insert_text((72, 72), long_text, fontsize=8)

        page1 = doc.new_page()
        page1.insert_text((72, 72), "Tiny", fontsize=12)
        img_doc = fitz.open()
        img_page = img_doc.new_page(width=50, height=50)
        pix = img_page.get_pixmap()
        img_bytes = pix.tobytes("png")
        img_doc.close()
        page1.insert_image(fitz.Rect(0, 0, 50, 50), stream=img_bytes)

        pdf_path = tmp_path / "mixed.pdf"
        doc.save(str(pdf_path))
        doc.close()

        result = extract_pdf(pdf_path)

        assert 0 not in result.ocr_pages
        assert 1 in result.ocr_pages
