"""Tests for PDFTextExtractor: valid, scanned, malformed, and encrypted PDF handling."""
from __future__ import annotations

from pathlib import Path

import pytest

from ingest.syllabus.extractor import PDFTextExtractor
from ingest.syllabus.models import (
    DownloadStatus,
    ExtractionStatus,
    SyllabusDocumentRecord,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _make_downloaded_doc(
    file_path: str | None = None,
    source_url: str = "https://hb2504.txst.edu/syllabi/CS1428.pdf",
    download_status: str = DownloadStatus.DOWNLOADED,
) -> SyllabusDocumentRecord:
    return SyllabusDocumentRecord(
        syllabus_id="00000000-0000-0000-0000-000000000001",
        source_url=source_url,
        file_path=file_path,
        content_type="application/pdf",
        content_hash="abc123hash",
        file_size=1024,
        download_status=download_status,
        manual_review_required=False,
    )


class TestPDFTextExtractor:
    def test_extract_valid_syllabus_fixture(self):
        pdf_path = FIXTURES / "valid_syllabus.pdf"
        doc = _make_downloaded_doc(file_path=str(pdf_path))
        extractor = PDFTextExtractor()

        result = extractor.extract_text(doc, pdf_path)

        assert result.extraction_status == ExtractionStatus.SUCCESS
        assert result.manual_review_required is False
        assert result.manual_review_reason is None
        assert result.page_count == 1
        assert result.character_count is not None and result.character_count > 100
        assert result.extracted_text is not None
        assert "CS 1428" in result.extracted_text
        assert "Grading Breakdown" in result.extracted_text
        assert "Required Textbook" in result.extracted_text

    def test_extract_scanned_syllabus_fixture(self):
        """Scanned image PDF fixture: has a page but no text layer.

        Must NOT be silently treated as empty text. Must be flagged for
        manual review with status SCANNED_NEEDS_OCR.
        """
        pdf_path = FIXTURES / "scanned_syllabus.pdf"
        doc = _make_downloaded_doc(file_path=str(pdf_path))
        extractor = PDFTextExtractor(min_chars_threshold=50)

        result = extractor.extract_text(doc, pdf_path)

        assert result.extraction_status == ExtractionStatus.SCANNED_NEEDS_OCR
        assert result.manual_review_required is True
        assert result.extracted_text is None  # MUST NOT silently be empty string!
        assert result.page_count == 1
        assert result.character_count == 0
        assert "scanned image" in result.manual_review_reason.lower()
        assert "ocr" in result.manual_review_reason.lower()

    def test_extract_malformed_corrupt_fixture(self):
        """Malformed/corrupt PDF fixture.

        Must NOT crash or treat as empty text; must be routed to manual review.
        """
        pdf_path = FIXTURES / "malformed_corrupt.pdf"
        doc = _make_downloaded_doc(file_path=str(pdf_path))
        extractor = PDFTextExtractor()

        result = extractor.extract_text(doc, pdf_path)

        assert result.extraction_status == ExtractionStatus.MALFORMED_PDF
        assert result.manual_review_required is True
        assert result.extracted_text is None
        assert "malformed" in result.manual_review_reason.lower()

    def test_extract_encrypted_pdf_fixture(self):
        """Encrypted PDF fixture.

        Must be identified as password-protected and routed to manual review.
        """
        pdf_path = FIXTURES / "encrypted_syllabus.pdf"
        doc = _make_downloaded_doc(file_path=str(pdf_path))
        extractor = PDFTextExtractor()

        result = extractor.extract_text(doc, pdf_path)

        assert result.extraction_status == ExtractionStatus.PASSWORD_PROTECTED
        assert result.manual_review_required is True
        assert result.extracted_text is None
        assert "password" in result.manual_review_reason.lower()

    def test_extract_from_bytes(self):
        pdf_bytes = (FIXTURES / "valid_syllabus.pdf").read_bytes()
        doc = _make_downloaded_doc()
        extractor = PDFTextExtractor()

        result = extractor.extract_text(doc, pdf_bytes)

        assert result.extraction_status == ExtractionStatus.SUCCESS
        assert result.extracted_text is not None
        assert "Jane Doe" in result.extracted_text

    def test_missing_file_on_disk(self, tmp_path):
        non_existent = tmp_path / "does_not_exist.pdf"
        doc = _make_downloaded_doc(file_path=str(non_existent))
        extractor = PDFTextExtractor()

        result = extractor.extract_text(doc, non_existent)

        assert result.extraction_status == ExtractionStatus.EXTRACTION_FAILED
        assert result.manual_review_required is True
        assert "missing" in result.manual_review_reason.lower()

    def test_undownloaded_doc_skips_extraction(self):
        doc = _make_downloaded_doc(download_status=DownloadStatus.MISSING)
        extractor = PDFTextExtractor()

        result = extractor.extract_text(doc, b"%PDF-dummy")

        assert result.extraction_status == ExtractionStatus.EXTRACTION_FAILED
        assert "un-downloaded" in result.error_message

    def test_extract_zero_page_pdf(self):
        """0-page PDF must be routed to manual review, never treated as success with empty text."""
        from unittest.mock import MagicMock, patch

        doc = _make_downloaded_doc()
        extractor = PDFTextExtractor()

        mock_reader = MagicMock()
        mock_reader.is_encrypted = False
        mock_reader.pages = []  # 0 pages

        with patch("pypdf.PdfReader", return_value=mock_reader):
            result = extractor.extract_text(doc, b"%PDF-1.4 dummy")

        assert result.extraction_status == ExtractionStatus.MALFORMED_PDF
        assert result.manual_review_required is True
        assert result.extracted_text is None  # Never empty string!
        assert result.page_count == 0
        assert "0 pages" in result.manual_review_reason.lower()

    def test_all_failure_modes_never_represent_failure_as_empty_string(self):
        """Verify that all failure paths set extracted_text = None, never empty string."""
        doc = _make_downloaded_doc()
        extractor = PDFTextExtractor()

        # 1. Scanned fixture
        scanned_res = extractor.extract_text(doc, FIXTURES / "scanned_syllabus.pdf")
        assert scanned_res.manual_review_required is True
        assert scanned_res.extracted_text is None

        # 2. Malformed fixture
        malformed_res = extractor.extract_text(doc, FIXTURES / "malformed_corrupt.pdf")
        assert malformed_res.manual_review_required is True
        assert malformed_res.extracted_text is None

        # 3. Encrypted fixture
        encrypted_res = extractor.extract_text(doc, FIXTURES / "encrypted_syllabus.pdf")
        assert encrypted_res.manual_review_required is True
        assert encrypted_res.extracted_text is None
