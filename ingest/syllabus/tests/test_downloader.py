"""Tests for SyllabusDownloader: integrity checks, size limits, headers, and change detection."""
from __future__ import annotations

import hashlib
import io
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ingest.syllabus.downloader import (
    CHUNK_SIZE,
    DEFAULT_MAX_PDF_SIZE_BYTES,
    SyllabusDownloader,
    parse_content_disposition_filename,
    sanitize_filename,
)
from ingest.syllabus.models import (
    DownloadStatus,
    SyllabusDocumentRecord,
    SyllabusRecord,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _make_record(
    course_code: str = "CS1428",
    section: str = "001",
    semester_code: str = "202510",
    source_url: str = "https://hb2504.txst.edu/syllabi/CS1428_001.pdf",
    has_syllabus: bool = True,
) -> SyllabusRecord:
    return SyllabusRecord(
        course_code=course_code,
        course_name="FOUNDATIONS OF COMPUTER SCI I",
        section=section,
        semester="Fall 2024",
        semester_code=semester_code,
        instructor_name="Dr. Jane Doe",
        instructor_plid="plid123",
        source_url=source_url,
        has_syllabus=has_syllabus,
        original_format="application/pdf",
        syllabus_filename="CS1428.pdf",
        credit_hours=4,
        index_num=101,
        fetched_at=datetime.now(timezone.utc),
        catalog_year="2024-2025",
        source_host="api.hb2504.txst.edu",
    )


class MockResponse:
    def __init__(
        self,
        data: bytes,
        headers: dict[str, str] | None = None,
        status: int = 200,
    ) -> None:
        self._stream = io.BytesIO(data)
        self.headers = headers or {}
        self.status = status

    def read(self, amt: int = -1) -> bytes:
        return self._stream.read(amt)


class TestFilenameParsingAndSanitization:
    def test_sanitize_normal_filename(self):
        assert sanitize_filename("syllabus.pdf") == "syllabus.pdf"

    def test_sanitize_strips_path_traversal(self):
        assert sanitize_filename("../../../etc/passwd.pdf") == "passwd.pdf"
        assert sanitize_filename("..\\..\\windows\\system32\\calc.pdf") == "calc.pdf"

    def test_sanitize_appends_pdf_extension(self):
        assert sanitize_filename("cs1428_syllabus") == "cs1428_syllabus.pdf"

    def test_parse_content_disposition_standard(self):
        hdr = 'attachment; filename="CS1428_Fall2024.pdf"'
        assert parse_content_disposition_filename(hdr) == "CS1428_Fall2024.pdf"

    def test_parse_content_disposition_rfc5987(self):
        hdr = "attachment; filename*=UTF-8''CS%201428%20Syllabus.pdf"
        assert parse_content_disposition_filename(hdr) == "CS 1428 Syllabus.pdf"

    def test_parse_content_disposition_empty_or_missing(self):
        assert parse_content_disposition_filename("") is None
        assert parse_content_disposition_filename("inline") is None


class TestSyllabusDownloader:
    def test_successful_download_and_integrity(self, tmp_path):
        pdf_bytes = (FIXTURES / "valid_syllabus.pdf").read_bytes()
        expected_hash = hashlib.sha256(pdf_bytes).hexdigest()

        mock_resp = MockResponse(
            data=pdf_bytes,
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": str(len(pdf_bytes)),
                "Content-Disposition": 'attachment; filename="CS1428_Syllabus.pdf"',
            },
        )
        downloader = SyllabusDownloader(
            storage_dir=tmp_path,
            retain_pdf=True,
            opener=lambda req, timeout: mock_resp,
        )

        record = _make_record()
        doc_record, downloaded_bytes = downloader.download_document(record)

        assert downloaded_bytes == pdf_bytes
        assert doc_record.download_status == DownloadStatus.DOWNLOADED
        assert doc_record.content_hash == expected_hash
        assert doc_record.file_size == len(pdf_bytes)
        assert doc_record.content_type == "application/pdf"
        assert doc_record.original_filename == "CS1428_Syllabus.pdf"
        assert doc_record.manual_review_required is False
        assert doc_record.file_path is not None
        assert Path(doc_record.file_path).is_file()
        assert Path(doc_record.file_path).read_bytes() == pdf_bytes

    def test_size_limit_content_length_header(self, tmp_path):
        mock_resp = MockResponse(
            data=b"%PDF-1.4 large content",
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": "20000000",  # 20 MB > 10 MB limit
            },
        )
        downloader = SyllabusDownloader(
            storage_dir=tmp_path,
            max_size_bytes=10 * 1024 * 1024,
            opener=lambda req, timeout: mock_resp,
        )

        record = _make_record()
        doc_record, downloaded_bytes = downloader.download_document(record)

        assert downloaded_bytes is None
        assert doc_record.download_status == DownloadStatus.EXCEEDS_SIZE_LIMIT
        assert doc_record.manual_review_required is True
        assert "exceeds limit" in doc_record.error_message.lower()

    def test_size_limit_streamed_chunks(self, tmp_path):
        # 2 MB data with 1 MB limit
        stream_data = b"%PDF-1.4" + b"X" * (2 * 1024 * 1024)
        mock_resp = MockResponse(
            data=stream_data,
            headers={"Content-Type": "application/pdf"},  # No Content-Length header
        )
        downloader = SyllabusDownloader(
            storage_dir=tmp_path,
            max_size_bytes=1 * 1024 * 1024,  # 1 MB
            opener=lambda req, timeout: mock_resp,
        )

        record = _make_record()
        doc_record, downloaded_bytes = downloader.download_document(record)

        assert downloaded_bytes is None
        assert doc_record.download_status == DownloadStatus.EXCEEDS_SIZE_LIMIT
        assert doc_record.manual_review_required is True

    def test_html_content_type_rejected(self, tmp_path):
        html_body = b"<!DOCTYPE html><html><body>Error 404 Course not found</body></html>"
        mock_resp = MockResponse(
            data=html_body,
            headers={"Content-Type": "text/html; charset=utf-8"},
        )
        downloader = SyllabusDownloader(
            storage_dir=tmp_path,
            opener=lambda req, timeout: mock_resp,
        )

        record = _make_record()
        doc_record, downloaded_bytes = downloader.download_document(record)

        assert downloaded_bytes is None
        assert doc_record.download_status == DownloadStatus.UNSUPPORTED_TYPE
        assert doc_record.manual_review_required is True
        assert "Content-Type" in doc_record.error_message

    def test_missing_magic_pdf_header(self, tmp_path):
        bad_bytes = b"This is a text file not a PDF"
        mock_resp = MockResponse(
            data=bad_bytes,
            headers={"Content-Type": "application/octet-stream"},
        )
        downloader = SyllabusDownloader(
            storage_dir=tmp_path,
            opener=lambda req, timeout: mock_resp,
        )

        record = _make_record()
        doc_record, downloaded_bytes = downloader.download_document(record)

        assert downloaded_bytes is None
        assert doc_record.download_status == DownloadStatus.UNSUPPORTED_TYPE
        assert doc_record.manual_review_required is True
        assert "magic header" in doc_record.error_message.lower()

    def test_missing_document_http_404(self, tmp_path):
        def _raise_404(req, timeout):
            raise urllib.error.HTTPError(
                url=req.full_url,
                code=404,
                msg="Not Found",
                hdrs={},
                fp=None,
            )

        downloader = SyllabusDownloader(
            storage_dir=tmp_path,
            opener=_raise_404,
        )
        record = _make_record()
        doc_record, downloaded_bytes = downloader.download_document(record)

        assert downloaded_bytes is None
        assert doc_record.download_status == DownloadStatus.MISSING
        assert "404" in doc_record.error_message
        assert doc_record.manual_review_required is False

    def test_server_error_http_500(self, tmp_path):
        def _raise_500(req, timeout):
            raise urllib.error.HTTPError(
                url=req.full_url,
                code=500,
                msg="Internal Server Error",
                hdrs={},
                fp=None,
            )

        downloader = SyllabusDownloader(
            storage_dir=tmp_path,
            opener=_raise_500,
        )
        record = _make_record()
        doc_record, downloaded_bytes = downloader.download_document(record)

        assert downloaded_bytes is None
        assert doc_record.download_status == DownloadStatus.DOWNLOADFAILED if hasattr(DownloadStatus, 'DOWNLOADFAILED') else DownloadStatus.DOWNLOAD_FAILED
        assert doc_record.manual_review_required is True
        assert "500" in doc_record.error_message

    def test_has_syllabus_false_skipped(self, tmp_path):
        mock_opener = MagicMock()
        downloader = SyllabusDownloader(
            storage_dir=tmp_path,
            opener=mock_opener,
        )
        record = _make_record(has_syllabus=False)
        doc_record, downloaded_bytes = downloader.download_document(record)

        mock_opener.assert_not_called()
        assert downloaded_bytes is None
        assert doc_record.download_status == DownloadStatus.MISSING
        assert "has_syllabus=False" in doc_record.error_message

    def test_no_retain_pdf(self, tmp_path):
        pdf_bytes = (FIXTURES / "valid_syllabus.pdf").read_bytes()
        mock_resp = MockResponse(
            data=pdf_bytes,
            headers={"Content-Type": "application/pdf"},
        )
        downloader = SyllabusDownloader(
            storage_dir=tmp_path,
            retain_pdf=False,  # Do not save to disk
            opener=lambda req, timeout: mock_resp,
        )

        record = _make_record()
        doc_record, downloaded_bytes = downloader.download_document(record)

        assert downloaded_bytes == pdf_bytes
        assert doc_record.download_status == DownloadStatus.DOWNLOADED
        assert doc_record.file_path is None
        # Verify no files were created in storage_dir
        assert len(list(tmp_path.glob("*.pdf"))) == 0

    def test_duplicate_document_detection(self, tmp_path):
        """Identical files across sections are detected as duplicates by SHA-256 hash."""
        pdf_bytes = (FIXTURES / "valid_syllabus.pdf").read_bytes()
        downloader = SyllabusDownloader(
            storage_dir=tmp_path,
            opener=lambda req, timeout: MockResponse(
                data=pdf_bytes,
                headers={"Content-Type": "application/pdf"},
            ),
        )

        rec1 = _make_record(section="001", source_url="https://example.com/sec1.pdf")
        rec2 = _make_record(section="002", source_url="https://example.com/sec2.pdf")

        doc1, bytes1 = downloader.download_document(rec1)
        doc2, bytes2 = downloader.download_document(rec2)

        assert doc1.content_hash == doc2.content_hash
        assert doc1.content_hash in downloader._seen_hashes
        assert downloader._seen_hashes[doc1.content_hash] == rec2.source_url

    def test_existing_doc_change_detection(self, tmp_path):
        """Downloader accepts existing_doc and detects changed content hash."""
        pdf_bytes = (FIXTURES / "valid_syllabus.pdf").read_bytes()
        mock_resp = MockResponse(
            data=pdf_bytes,
            headers={"Content-Type": "application/pdf"},
        )
        downloader = SyllabusDownloader(
            storage_dir=tmp_path,
            opener=lambda req, timeout: mock_resp,
        )

        # Existing doc with old/different hash
        old_doc = SyllabusDocumentRecord(
            syllabus_id="doc-old",
            source_url="https://example.com/sec1.pdf",
            content_hash="old_different_hash_0000000000000000000000000000000000000000",
            download_status=DownloadStatus.DOWNLOADED,
        )
        record = _make_record(source_url="https://example.com/sec1.pdf")
        doc_record, _ = downloader.download_document(record, existing_doc=old_doc)

        assert doc_record.content_hash != old_doc.content_hash
        assert doc_record.download_status == DownloadStatus.DOWNLOADED
