"""Tests for Section 6 CLI options: download, reprocess, and manual review."""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingest.syllabus.cli import _run_pipeline
from ingest.syllabus.models import (
    DownloadStatus,
    ExtractionStatus,
    SyllabusDocumentRecord,
    SyllabusRecord,
    ValidationResult,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestCLISection6:
    @patch("ingest.syllabus.cli.list_manual_review_documents")
    def test_list_manual_review_flag(self, mock_list_docs, capsys):
        mock_list_docs.return_value = [
            {
                "document_id": "doc-uuid-1",
                "course_code": "CS1428",
                "section": "001",
                "semester": "Fall 2024",
                "instructor_name": "Dr. Doe",
                "download_status": "DOWNLOADED",
                "extraction_status": "SCANNED_NEEDS_OCR",
                "manual_review_reason": "Image-only scanned PDF",
                "source_url": "https://example.com/test.pdf",
                "file_path": "/tmp/test.pdf",
            }
        ]

        code = _run_pipeline(
            apply=False,
            database_url="postgresql://fake/db",
            max_semesters=None,
            probe_syllabi=False,
            fail_on_fetch_errors=False,
            verbose=False,
            catalog_year=None,
            list_manual_review=True,
        )

        assert code == 0
        captured = capsys.readouterr().out
        assert "MANUAL REVIEW QUEUE" in captured
        assert "CS1428" in captured
        assert "SCANNED_NEEDS_OCR" in captured
        assert "Image-only scanned PDF" in captured

    @patch("ingest.syllabus.cli.resolve_manual_review")
    def test_resolve_manual_review_flag(self, mock_resolve, tmp_path, capsys):
        mock_resolve.return_value = True
        text_file = tmp_path / "manual_syllabus.txt"
        text_file.write_text("Grading: Exams 50%, Homework 50%", encoding="utf-8")

        code = _run_pipeline(
            apply=False,
            database_url="postgresql://fake/db",
            max_semesters=None,
            probe_syllabi=False,
            fail_on_fetch_errors=False,
            verbose=False,
            catalog_year=None,
            resolve_review_id="doc-uuid-1",
            manual_notes="Reviewed and transcribed text",
            manual_text_file=str(text_file),
        )

        assert code == 0
        captured = capsys.readouterr().out
        assert "Successfully resolved manual review for document doc-uuid-1" in captured
        mock_resolve.assert_called_once_with(
            document_id="doc-uuid-1",
            notes="Reviewed and transcribed text",
            manual_text="Grading: Exams 50%, Homework 50%",
            database_url="postgresql://fake/db",
        )

    @patch("ingest.syllabus.cli.HB2504Fetcher")
    @patch("ingest.syllabus.cli.SyllabusDownloader")
    def test_dry_run_with_download_syllabi(self, mock_downloader_cls, mock_fetcher_cls, capsys):
        # Mock fetcher
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_cs_courses.return_value = [{"number": "CS1428", "title": "FOUNDATIONS"}]
        mock_fetcher.fetch_course_details.return_value = {
            "credit_hours": 4,
            "semesters": [202510],
        }
        mock_fetcher.fetch_classes.return_value = [
            {
                "section": "001",
                "syllabus": True,
                "indexnum": 1001,
                "instructors": [],
            }
        ]
        mock_fetcher_cls.return_value = mock_fetcher

        # Mock downloader
        pdf_bytes = (FIXTURES / "valid_syllabus.pdf").read_bytes()
        mock_downloader = MagicMock()
        mock_doc = SyllabusDocumentRecord(
            syllabus_id="doc-123",
            source_url="https://example.com/cs1428.pdf",
            download_status=DownloadStatus.DOWNLOADED,
            content_type="application/pdf",
            content_hash="mockhash123",
            file_size=len(pdf_bytes),
        )
        mock_downloader.download_document.return_value = (mock_doc, pdf_bytes)
        mock_downloader_cls.return_value = mock_downloader

        code = _run_pipeline(
            apply=False,
            database_url=None,
            max_semesters=1,
            probe_syllabi=False,
            fail_on_fetch_errors=False,
            verbose=False,
            catalog_year="2024-2025",
            download_syllabi=True,
        )

        assert code == 0
        captured = capsys.readouterr().out
        assert "PDF Download & Extraction Preview" in captured
        assert "Extraction SUCCESS: 1" in captured
        assert "Extracted Observations" in captured
        assert "Re-run with --apply to write to the database" in captured

    @patch("ingest.syllabus.cli.HB2504Fetcher")
    @patch("ingest.syllabus.cli.SyllabusDownloader")
    def test_has_syllabus_false_sections_not_downloaded(
        self, mock_downloader_cls, mock_fetcher_cls, capsys
    ):
        """Sections with has_syllabus=False are kept as metadata and never downloaded."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_cs_courses.return_value = [{"number": "CS1428", "title": "FOUNDATIONS"}]
        mock_fetcher.fetch_course_details.return_value = {"credit_hours": 4, "semesters": [202510]}
        mock_fetcher.fetch_classes.return_value = [
            {"section": "001", "syllabus": False, "indexnum": 1001, "instructors": []},
            {"section": "002", "syllabus": True, "indexnum": 1002, "instructors": []},
        ]
        mock_fetcher_cls.return_value = mock_fetcher

        pdf_bytes = (FIXTURES / "valid_syllabus.pdf").read_bytes()
        mock_downloader = MagicMock()
        mock_doc = SyllabusDocumentRecord(
            syllabus_id="doc-1002",
            source_url="https://api.hb2504.txst.edu/py/getsyllabus.py?course=CS1428&semester=202510&section=002",
            download_status=DownloadStatus.DOWNLOADED,
            content_type="application/pdf",
            content_hash="mockhash002",
            file_size=len(pdf_bytes),
        )
        mock_downloader.download_document.return_value = (mock_doc, pdf_bytes)
        mock_downloader_cls.return_value = mock_downloader

        code = _run_pipeline(
            apply=False,
            database_url=None,
            max_semesters=1,
            probe_syllabi=False,
            fail_on_fetch_errors=False,
            verbose=False,
            catalog_year=None,
            download_syllabi=True,
        )

        assert code == 0
        # Exactly 1 download call for section 002 (section 001 with has_syllabus=False is skipped)
        assert mock_downloader.download_document.call_count == 1
        called_rec = mock_downloader.download_document.call_args[0][0]
        assert called_rec.section == "002"
        assert called_rec.has_syllabus is True

        captured = capsys.readouterr().out
        assert "Total valid records: 2" in captured
        assert "No-syllabus rows: 1" in captured

    @patch("ingest.syllabus.cli.get_document_by_source_url")
    @patch("ingest.syllabus.cli.HB2504Fetcher")
    @patch("ingest.syllabus.cli.SyllabusDownloader")
    def test_skip_unchanged_document_by_hash(
        self, mock_downloader_cls, mock_fetcher_cls, mock_get_doc, capsys
    ):
        """Unchanged document with matching SHA-256 hash skips re-extraction."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_cs_courses.return_value = [{"number": "CS1428", "title": "FOUNDATIONS"}]
        mock_fetcher.fetch_course_details.return_value = {"credit_hours": 4, "semesters": [202510]}
        mock_fetcher.fetch_classes.return_value = [
            {"section": "001", "syllabus": True, "indexnum": 1001, "instructors": []}
        ]
        mock_fetcher_cls.return_value = mock_fetcher

        pdf_bytes = (FIXTURES / "valid_syllabus.pdf").read_bytes()
        mock_downloader = MagicMock()
        mock_doc = SyllabusDocumentRecord(
            syllabus_id="doc-123",
            source_url="https://api.hb2504.txst.edu/py/getsyllabus.py?course=CS1428&semester=202510&section=001",
            download_status=DownloadStatus.DOWNLOADED,
            content_type="application/pdf",
            content_hash="matching_hash_123",
            file_size=len(pdf_bytes),
        )
        mock_downloader.download_document.return_value = (mock_doc, pdf_bytes)
        mock_downloader_cls.return_value = mock_downloader

        # Existing doc in DB has identical content_hash and SUCCESS extraction
        mock_get_doc.return_value = SyllabusDocumentRecord(
            syllabus_id="doc-123",
            source_url=mock_doc.source_url,
            content_hash="matching_hash_123",
            download_status=DownloadStatus.DOWNLOADED,
            extraction_status=ExtractionStatus.SUCCESS,
            extracted_text="Already extracted text",
        )

        code = _run_pipeline(
            apply=False,
            database_url="postgresql://fake/db",
            max_semesters=1,
            probe_syllabi=False,
            fail_on_fetch_errors=False,
            verbose=False,
            catalog_year=None,
            download_syllabi=True,
            reprocess=False,
        )

        assert code == 0
        captured = capsys.readouterr().out
        assert "Unchanged Documents Skipped (by hash): 1" in captured

    @patch("ingest.syllabus.cli.load_documents_and_observations")
    @patch("ingest.syllabus.cli.load_records")
    @patch("ingest.syllabus.cli.HB2504Fetcher")
    @patch("ingest.syllabus.cli.SyllabusDownloader")
    def test_apply_mode_calls_transactional_loader(
        self, mock_downloader_cls, mock_fetcher_cls, mock_load_records, mock_load_docs_obs, capsys
    ):
        """Applying with --download-syllabi invokes load_documents_and_observations."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_cs_courses.return_value = [{"number": "CS1428", "title": "FOUNDATIONS"}]
        mock_fetcher.fetch_course_details.return_value = {"credit_hours": 4, "semesters": [202510]}
        mock_fetcher.fetch_classes.return_value = [
            {"section": "001", "syllabus": True, "indexnum": 1001, "instructors": []}
        ]
        mock_fetcher_cls.return_value = mock_fetcher

        pdf_bytes = (FIXTURES / "valid_syllabus.pdf").read_bytes()
        mock_downloader = MagicMock()
        mock_doc = SyllabusDocumentRecord(
            syllabus_id="doc-123",
            source_url="https://api.hb2504.txst.edu/py/getsyllabus.py?course=CS1428&semester=202510&section=001",
            download_status=DownloadStatus.DOWNLOADED,
            content_type="application/pdf",
            content_hash="mockhash123",
            file_size=len(pdf_bytes),
        )
        mock_downloader.download_document.return_value = (mock_doc, pdf_bytes)
        mock_downloader_cls.return_value = mock_downloader

        mock_load_records.return_value = 1
        mock_load_docs_obs.return_value = (1, 4)

        code = _run_pipeline(
            apply=True,
            database_url="postgresql://fake/db",
            max_semesters=1,
            probe_syllabi=False,
            fail_on_fetch_errors=False,
            verbose=False,
            catalog_year=None,
            download_syllabi=True,
        )

        assert code == 0
        mock_load_records.assert_called_once()
        mock_load_docs_obs.assert_called_once()
        captured = capsys.readouterr().out
        assert "Successfully upserted 1 syllabus documents and 4 structured observations." in captured
