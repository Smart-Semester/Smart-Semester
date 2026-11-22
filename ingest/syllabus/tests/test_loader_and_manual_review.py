"""Tests for loader functions: documents, observations, and manual review workflow."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from ingest.syllabus.loader import (
    get_document_by_content_hash,
    get_document_by_source_url,
    list_manual_review_documents,
    load_documents_and_observations,
    load_observations,
    load_records,
    resolve_manual_review,
    upsert_syllabus_document,
)
from ingest.syllabus.models import (
    DownloadStatus,
    ExtractionStatus,
    ObservationRecord,
    SyllabusDocumentRecord,
    SyllabusRecord,
)


def _make_sample_doc(
    source_url: str = "https://hb2504.txst.edu/syllabi/CS1428_test.pdf",
    manual_review: bool = True,
) -> SyllabusDocumentRecord:
    return SyllabusDocumentRecord(
        syllabus_id="11111111-1111-1111-1111-111111111111",
        source_url=source_url,
        file_path="data/syllabi/CS1428_test.pdf",
        content_type="application/pdf",
        original_filename="CS1428.pdf",
        content_hash="hash123456",
        file_size=2048,
        download_status=DownloadStatus.DOWNLOADED,
        extraction_status=ExtractionStatus.SCANNED_NEEDS_OCR if manual_review else ExtractionStatus.SUCCESS,
        extracted_text=None if manual_review else "Sample text",
        manual_review_required=manual_review,
        manual_review_reason="Scanned PDF needs OCR" if manual_review else None,
        downloaded_at=datetime.now(timezone.utc),
    )


class TestLoaderOfflineWithMocks:
    def _setup_mock_conn(self, mock_connect):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_cur.__enter__.return_value = mock_cur
        mock_conn.cursor.return_value = mock_cur
        mock_connect.return_value = mock_conn
        return mock_conn, mock_cur

    @patch("psycopg2.connect")
    def test_upsert_syllabus_document(self, mock_connect):
        mock_conn, mock_cur = self._setup_mock_conn(mock_connect)
        mock_cur.fetchone.return_value = ("22222222-2222-2222-2222-222222222222",)

        doc = _make_sample_doc()
        doc_id = upsert_syllabus_document(doc, "postgresql://fake:fake@localhost/db")

        assert doc_id == "22222222-2222-2222-2222-222222222222"
        mock_cur.execute.assert_called_once()
        sql, params = mock_cur.execute.call_args[0]
        assert "INSERT INTO catalog.syllabus_documents" in sql
        assert params["source_url"] == doc.source_url
        assert params["content_hash"] == doc.content_hash
        assert params["manual_review_required"] is True

    @patch("psycopg2.connect")
    def test_load_observations(self, mock_connect):
        mock_conn, mock_cur = self._setup_mock_conn(mock_connect)

        obs = [
            ObservationRecord(
                syllabus_id="11111111-1111-1111-1111-111111111111",
                course_code="CS1428",
                semester_code="202510",
                category="grading_breakdown",
                observation_key="Exams",
                observation_value="50%",
                context_snippet="Exams: 50%",
                confidence=0.95,
                provenance={"source_url": "https://example.com/test.pdf"},
                document_id="22222222-2222-2222-2222-222222222222",
            )
        ]
        count = load_observations(obs, "postgresql://fake:fake@localhost/db")

        assert count == 1
        # 1 call to DELETE previous observations (idempotency) + 1 call to INSERT
        assert mock_cur.execute.call_count == 2
        delete_sql, delete_params = mock_cur.execute.call_args_list[0][0]
        assert "DELETE FROM catalog.syllabus_observations" in delete_sql
        assert delete_params == ("22222222-2222-2222-2222-222222222222",)

        insert_sql, params = mock_cur.execute.call_args_list[1][0]
        assert "INSERT INTO catalog.syllabus_observations" in insert_sql
        assert params["category"] == "grading_breakdown"
        assert params["observation_key"] == "Exams"
        assert params["observation_value"] == "50%"

    @patch("psycopg2.connect")
    def test_list_manual_review_documents(self, mock_connect):
        mock_conn, mock_cur = self._setup_mock_conn(mock_connect)
        mock_cur.description = [
            ("document_id",), ("syllabus_id",), ("course_code",), ("section",),
            ("semester",), ("semester_code",), ("instructor_name",), ("source_url",),
            ("file_path",), ("content_type",), ("download_status",), ("extraction_status",),
            ("manual_review_reason",), ("manual_review_notes",), ("error_message",),
            ("created_at",)
        ]
        mock_cur.fetchall.return_value = [
            (
                "22222222-2222-2222-2222-222222222222",
                "11111111-1111-1111-1111-111111111111",
                "CS1428", "001", "Fall 2024", "202510", "Dr. Jane Doe",
                "https://example.com/test.pdf", "/path/to/test.pdf", "application/pdf",
                "DOWNLOADED", "SCANNED_NEEDS_OCR", "Scanned PDF needs OCR", None, None,
                datetime.now(timezone.utc),
            )
        ]

        items = list_manual_review_documents("postgresql://fake:fake@localhost/db")

        assert len(items) == 1
        assert items[0]["course_code"] == "CS1428"
        assert items[0]["extraction_status"] == "SCANNED_NEEDS_OCR"

    @patch("psycopg2.connect")
    def test_resolve_manual_review(self, mock_connect):
        mock_conn, mock_cur = self._setup_mock_conn(mock_connect)
        mock_cur.rowcount = 1

        ok = resolve_manual_review(
            document_id="22222222-2222-2222-2222-222222222222",
            notes="Manually verified syllabus text",
            manual_text="Transcribed course text",
            database_url="postgresql://fake:fake@localhost/db",
        )

        assert ok is True
        mock_cur.execute.assert_called_once()
        sql, params = mock_cur.execute.call_args[0]
        assert "manual_review_required = FALSE" in sql
        assert params["notes"] == "Manually verified syllabus text"
        assert params["manual_text"] == "Transcribed course text"

    @patch("psycopg2.connect")
    def test_load_documents_and_observations_transactional(self, mock_connect):
        mock_conn, mock_cur = self._setup_mock_conn(mock_connect)
        mock_cur.fetchone.side_effect = [
            ("22222222-2222-2222-2222-222222222222",),  # doc upsert returning doc_id
            ("11111111-1111-1111-1111-111111111111",),  # select syllabus_id
        ]

        doc = _make_sample_doc(manual_review=False)
        obs = [
            ObservationRecord(
                syllabus_id="11111111-1111-1111-1111-111111111111",
                course_code="CS1428",
                semester_code="202510",
                category="textbook",
                observation_key="Required Textbook",
                observation_value="Tony Gaddis C++",
                context_snippet="Required Textbook: Tony Gaddis C++",
                confidence=0.90,
                provenance={"source_url": doc.source_url},
                document_id="22222222-2222-2222-2222-222222222222",
            )
        ]

        docs_count, obs_count = load_documents_and_observations(
            [(doc, obs)], "postgresql://fake:fake@localhost/db"
        )

        assert docs_count == 1
        assert obs_count == 1
        # Calls: 1 doc upsert, 1 observation delete, 1 select syllabus_id, 1 observation insert
        assert mock_cur.execute.call_count == 4
        calls = [c[0][0] for c in mock_cur.execute.call_args_list]
        assert any("INSERT INTO catalog.syllabus_documents" in c for c in calls)
        assert any("DELETE FROM catalog.syllabus_observations WHERE document_id" in c for c in calls)
        assert any("INSERT INTO catalog.syllabus_observations" in c for c in calls)

    @patch("psycopg2.connect")
    def test_get_document_by_content_hash(self, mock_connect):
        mock_conn, mock_cur = self._setup_mock_conn(mock_connect)
        mock_cur.fetchone.return_value = (
            "22222222-2222-2222-2222-222222222222",
            "11111111-1111-1111-1111-111111111111",
            "https://example.com/test.pdf",
            "/path/to/test.pdf",
            "application/pdf",
            "test.pdf",
            "hash123456",
            2048,
            "DOWNLOADED",
            "SUCCESS",
            "Sample text",
            2,
            500,
            None,
            False,
            None,
            None,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
        )

        doc = get_document_by_content_hash("hash123456", "postgresql://fake:fake@localhost/db")

        assert doc is not None
        assert doc.content_hash == "hash123456"
        assert doc.extraction_status == "SUCCESS"


# ── Live Integration Tests (executed if DATABASE_URL is available) ───────────

DATABASE_URL = os.environ.get("DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set for live DB test")
class TestLiveDatabaseIntegration:
    def test_end_to_end_db_workflow(self):
        import psycopg2

        # 1. Upsert a test syllabus record
        test_url = "https://hb2504.txst.edu/syllabi/CS1428_live_test.pdf"
        record = SyllabusRecord(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            section="099",
            semester="Fall 2024",
            semester_code="202510",
            instructor_name="Dr. Test",
            instructor_plid="plid_test",
            source_url=test_url,
            has_syllabus=True,
            original_format="application/pdf",
            syllabus_filename="test.pdf",
            credit_hours=4,
            index_num=99999,
            fetched_at=datetime.now(timezone.utc),
            catalog_year="2024-2025",
            source_host="api.hb2504.txst.edu",
        )
        load_records([record], DATABASE_URL)

        # 2. Upsert document needing manual review
        doc = SyllabusDocumentRecord(
            syllabus_id=test_url,  # will resolve via subquery
            source_url=test_url,
            file_path="data/syllabi/test.pdf",
            content_type="application/pdf",
            original_filename="test.pdf",
            content_hash="live_hash_abc",
            file_size=1234,
            download_status=DownloadStatus.DOWNLOADED,
            extraction_status=ExtractionStatus.SCANNED_NEEDS_OCR,
            extracted_text=None,
            manual_review_required=True,
            manual_review_reason="Live test scanned PDF",
            downloaded_at=datetime.now(timezone.utc),
        )
        doc_id = upsert_syllabus_document(doc, DATABASE_URL)
        assert doc_id is not None

        # 3. Query manual review queue
        items = list_manual_review_documents(DATABASE_URL)
        matching = [i for i in items if i["document_id"] == doc_id]
        assert len(matching) == 1
        assert matching[0]["course_code"] == "CS1428"
        assert matching[0]["extraction_status"] == ExtractionStatus.SCANNED_NEEDS_OCR

        # 4. Resolve manual review
        resolved = resolve_manual_review(
            document_id=doc_id,
            notes="Transcribed by testing harness",
            manual_text="Grading: Exams 50%, Homework 50%",
            database_url=DATABASE_URL,
        )
        assert resolved is True

        # 5. Insert observations with provenance
        obs = [
            ObservationRecord(
                document_id=doc_id,
                syllabus_id=test_url,
                course_code="CS1428",
                semester_code="202510",
                category="grading_breakdown",
                observation_key="Exams",
                observation_value="50%",
                context_snippet="Grading: Exams 50%",
                confidence=0.95,
                provenance={"source_url": test_url, "content_hash": "live_hash_abc"},
            )
        ]
        obs_count = load_observations(obs, DATABASE_URL)
        assert obs_count == 1

        # 6. Verify separation: catalog.courses remains official and unchanged
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT observation_key, observation_value FROM catalog.syllabus_observations WHERE document_id = %s",
                (doc_id,),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == "Exams"
            assert row[1] == "50%"

            # Verify manual review flag cleared
            cur.execute(
                "SELECT manual_review_required, extracted_text FROM catalog.syllabus_documents WHERE document_id = %s",
                (doc_id,),
            )
            doc_row = cur.fetchone()
            assert doc_row[0] is False
            assert "Grading: Exams 50%" in doc_row[1]
        conn.close()

    def test_transactional_and_idempotent_load_live(self):
        """Verify that load_documents_and_observations is atomic and idempotent in Postgres."""
        import psycopg2

        test_url = "https://hb2504.txst.edu/syllabi/CS1428_idempotent_live.pdf"
        record = SyllabusRecord(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            section="098",
            semester="Fall 2024",
            semester_code="202510",
            instructor_name="Dr. Idempotent",
            instructor_plid="plid_idem",
            source_url=test_url,
            has_syllabus=True,
            original_format="application/pdf",
            syllabus_filename="idem.pdf",
            credit_hours=4,
            index_num=99998,
            fetched_at=datetime.now(timezone.utc),
            catalog_year="2024-2025",
            source_host="api.hb2504.txst.edu",
        )
        load_records([record], DATABASE_URL)

        doc = SyllabusDocumentRecord(
            syllabus_id=test_url,
            source_url=test_url,
            file_path="data/syllabi/idem.pdf",
            content_type="application/pdf",
            original_filename="idem.pdf",
            content_hash="idem_hash_123",
            file_size=2000,
            download_status=DownloadStatus.DOWNLOADED,
            extraction_status=ExtractionStatus.SUCCESS,
            extracted_text="Programming Assignments: 40%\nMidterms: 60%",
            page_count=2,
            character_count=50,
            manual_review_required=False,
            downloaded_at=datetime.now(timezone.utc),
            extracted_at=datetime.now(timezone.utc),
        )

        obs = [
            ObservationRecord(
                syllabus_id=test_url,
                course_code="CS1428",
                semester_code="202510",
                category="grading_breakdown",
                observation_key="Programming Assignments",
                observation_value="40%",
                context_snippet="Programming Assignments: 40%",
                confidence=0.95,
                provenance={"source_url": test_url, "content_hash": "idem_hash_123"},
            ),
            ObservationRecord(
                syllabus_id=test_url,
                course_code="CS1428",
                semester_code="202510",
                category="grading_breakdown",
                observation_key="Midterms",
                observation_value="60%",
                context_snippet="Midterms: 60%",
                confidence=0.95,
                provenance={"source_url": test_url, "content_hash": "idem_hash_123"},
            ),
        ]

        # First run: writes 1 document and 2 observations
        d1, o1 = load_documents_and_observations([(doc, obs)], DATABASE_URL)
        assert d1 == 1
        assert o1 == 2

        # Second run (exact re-run): must be idempotent and NOT create duplicate observations
        d2, o2 = load_documents_and_observations([(doc, obs)], DATABASE_URL)
        assert d2 == 1
        assert o2 == 2

        # Verify DB contains exactly 2 observations (not 4)
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM catalog.syllabus_observations o
                JOIN catalog.syllabus_documents d ON d.document_id = o.document_id
                WHERE d.source_url = %s;
                """,
                (test_url,),
            )
            count = cur.fetchone()[0]
            assert count == 2, f"Expected 2 observations after repeated write, found {count}"
        conn.close()
