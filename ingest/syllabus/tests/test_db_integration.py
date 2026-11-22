"""Database integration tests for migrations, relationships, and idempotent upserts.

These tests use mock-based offline assertions to verify the SQL structure and
loader behavior without a live Postgres connection. Live tests that require
PostgreSQL are guarded by DATABASE_URL and use pytest.mark.skipif.

Covers:
- Migration SQL idempotency guards (IF NOT EXISTS, ADD COLUMN IF NOT EXISTS)
- Soft-FK relationship: syllabi.course_code is a logical reference (no hard FK)
- Idempotent upserts: inserting the same source_url twice updates, not duplicates
- Schema separation: observations stored separately from catalog.courses
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

try:
    import pytest
except ImportError:
    # Graceful fallback when pytest is not installed in the execution environment
    class _MockPytest:
        class mark:
            @staticmethod
            def skipif(cond, reason=""):
                def decorator(cls_or_fn):
                    if cond:
                        cls_or_fn.__unittest_skip__ = True
                        cls_or_fn.__unittest_skip_why__ = reason
                    return cls_or_fn
                return decorator
    pytest = _MockPytest()

try:
    import psycopg2
except ImportError:
    import sys
    from unittest.mock import MagicMock
    sys.modules["psycopg2"] = MagicMock()

from ingest.syllabus.loader import load_records, upsert_syllabus_document
from ingest.syllabus.models import (
    DownloadStatus,
    ExtractionStatus,
    SyllabusDocumentRecord,
    SyllabusRecord,
)

MIGRATIONS_DIR = Path(__file__).parents[3] / "init-db"
DATABASE_URL = os.environ.get("DATABASE_URL")


# ── Migration SQL structure tests (offline) ───────────────────────────────────


class TestMigrationIdempotencyGuards:
    """Verify that migration files contain the IF NOT EXISTS guards required
    for safe re-runs on both fresh and existing database volumes."""

    def test_migration_01_has_create_schema_if_not_exists(self):
        sql = (MIGRATIONS_DIR / "01-init.sql").read_text()
        assert "CREATE SCHEMA IF NOT EXISTS catalog" in sql
        assert "CREATE TABLE IF NOT EXISTS catalog.courses" in sql

    def test_migration_02_has_create_table_if_not_exists(self):
        sql = (MIGRATIONS_DIR / "02-syllabi.sql").read_text()
        assert "CREATE TABLE IF NOT EXISTS catalog.syllabi" in sql
        assert "CREATE INDEX IF NOT EXISTS" in sql

    def test_migration_03_has_add_column_if_not_exists(self):
        sql = (MIGRATIONS_DIR / "03-traceability.sql").read_text()
        assert "ADD COLUMN IF NOT EXISTS fetched_at" in sql
        assert "ADD COLUMN IF NOT EXISTS catalog_year" in sql
        assert "ADD COLUMN IF NOT EXISTS source_host" in sql

    def test_migration_04_has_add_column_if_not_exists(self):
        sql = (MIGRATIONS_DIR / "04-req-tree.sql").read_text()
        assert "ADD COLUMN IF NOT EXISTS prereq_tree" in sql
        assert "ADD COLUMN IF NOT EXISTS coreq_tree" in sql
        assert "ADD COLUMN IF NOT EXISTS requirements_parsed" in sql
        assert "CREATE INDEX IF NOT EXISTS" in sql

    def test_migration_05_has_do_block_guard(self):
        """Migration 05 uses a DO $$ IF NOT EXISTS block for the unique constraint."""
        sql = (MIGRATIONS_DIR / "05-uniqueness-and-fk.sql").read_text()
        assert "DO $$" in sql
        assert "IF NOT EXISTS" in sql
        assert "uq_courses_code_year" in sql
        assert "CREATE INDEX IF NOT EXISTS" in sql

    def test_migration_05_documents_soft_fk(self):
        """Migration 05 documents the syllabi→courses soft relationship via COMMENT."""
        sql = (MIGRATIONS_DIR / "05-uniqueness-and-fk.sql").read_text()
        assert "COMMENT ON COLUMN catalog.syllabi.course_code" in sql
        # No REFERENCES keyword — this confirms no hard FK was added
        assert "REFERENCES catalog.courses" not in sql

    def test_migration_06_exists_and_has_syllabus_documents(self):
        sql = (MIGRATIONS_DIR / "06-syllabus-documents-and-observations.sql").read_text()
        assert "catalog.syllabus_documents" in sql
        assert "catalog.syllabus_observations" in sql

    def test_migrations_all_present(self):
        """All six migration files must exist."""
        expected = [
            "01-init.sql",
            "02-syllabi.sql",
            "03-traceability.sql",
            "04-req-tree.sql",
            "05-uniqueness-and-fk.sql",
            "06-syllabus-documents-and-observations.sql",
        ]
        for name in expected:
            path = MIGRATIONS_DIR / name
            assert path.exists(), f"Migration file missing: {name}"

    def test_migrate_runner_exists(self):
        """The migrate.py runner must exist in init-db/."""
        assert (MIGRATIONS_DIR / "migrate.py").exists()


# ── Soft-FK relationship tests (offline) ─────────────────────────────────────


class TestSoftFKRelationship:
    """Verify the loader does not enforce a hard FK between syllabi and courses.

    The design decision (migration 05) is a soft relationship: syllabi can be
    ingested before the matching catalog course row exists. We verify this by
    checking the UPSERT_SQL does not reference catalog.courses, and that the
    loader can be called with a course_code that has no courses row.
    """

    def test_upsert_sql_has_no_foreign_key_to_courses(self):
        from ingest.syllabus.loader import UPSERT_SQL
        # The INSERT should target catalog.syllabi only, not catalog.courses
        assert "catalog.courses" not in UPSERT_SQL
        assert "REFERENCES" not in UPSERT_SQL

    @patch("psycopg2.connect")
    def test_load_records_succeeds_for_unknown_course_code(self, mock_connect):
        """A SyllabusRecord with a course_code not in catalog.courses must still upsert."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value = mock_cur
        mock_connect.return_value = mock_conn

        record = SyllabusRecord(
            course_code="CS9999",          # unknown code — not in catalog.courses
            course_name="NONEXISTENT COURSE",
            section="001",
            semester="Fall 2024",
            semester_code="202510",
            instructor_name=None,
            instructor_plid=None,
            source_url="https://api.hb2504.txst.edu/py/getsyllabus.py?class=99999",
            has_syllabus=True,
            original_format=None,
            syllabus_filename=None,
            credit_hours=3,
            index_num=99999,
            fetched_at=datetime.now(timezone.utc),
            catalog_year="2024-2025",
            source_host="api.hb2504.txst.edu",
        )
        # Should not raise — no FK check
        count = load_records([record], "postgresql://fake/db")
        assert count == 1
        mock_cur.execute.assert_called()


# ── Idempotent upsert tests (offline with mocks) ──────────────────────────────


class TestIdempotentUpserts:
    """Verify the loader's ON CONFLICT (source_url) DO UPDATE behavior."""

    def _make_conn_mock(self, mock_connect):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_conn.cursor.return_value = mock_cur
        mock_connect.return_value = mock_conn
        return mock_conn, mock_cur

    @patch("psycopg2.connect")
    def test_upsert_sql_uses_on_conflict(self, mock_connect):
        """The UPSERT_SQL must contain ON CONFLICT (source_url) DO UPDATE."""
        from ingest.syllabus.loader import UPSERT_SQL
        assert "ON CONFLICT (source_url) DO UPDATE" in UPSERT_SQL

    @patch("psycopg2.connect")
    def test_load_records_idempotent_second_call_does_not_raise(self, mock_connect):
        """Calling load_records twice with the same source_url must not raise."""
        mock_conn, mock_cur = self._make_conn_mock(mock_connect)

        record = SyllabusRecord(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            section="005",
            semester="Fall 2024",
            semester_code="202510",
            instructor_name="Test Instructor",
            instructor_plid="xtest",
            source_url="https://api.hb2504.txst.edu/py/getsyllabus.py?class=12345",
            has_syllabus=True,
            original_format=None,
            syllabus_filename=None,
            credit_hours=4,
            index_num=12345,
            fetched_at=datetime.now(timezone.utc),
            catalog_year="2024-2025",
            source_host="api.hb2504.txst.edu",
        )

        # First call
        count1 = load_records([record], "postgresql://fake/db")
        # Second call — same record, same source_url → upsert (no error)
        count2 = load_records([record], "postgresql://fake/db")

        assert count1 == 1
        assert count2 == 1
        # Both calls should have executed the upsert SQL
        assert mock_cur.execute.call_count == 2

    @patch("psycopg2.connect")
    def test_load_records_updated_at_in_upsert_sql(self, mock_connect):
        """The UPSERT_SQL must set updated_at = CURRENT_TIMESTAMP on conflict."""
        from ingest.syllabus.loader import UPSERT_SQL
        assert "updated_at" in UPSERT_SQL
        assert "CURRENT_TIMESTAMP" in UPSERT_SQL

    @patch("psycopg2.connect")
    def test_upsert_syllabus_document_on_conflict(self, mock_connect):
        """upsert_syllabus_document SQL must include ON CONFLICT DO UPDATE."""
        mock_conn, mock_cur = self._make_conn_mock(mock_connect)
        mock_cur.fetchone.return_value = ("doc-uuid-1",)

        doc = SyllabusDocumentRecord(
            syllabus_id="syl-uuid-1",
            source_url="https://example.com/CS1428_test.pdf",
            content_hash="abc123",
            download_status=DownloadStatus.DOWNLOADED,
            extraction_status=ExtractionStatus.SUCCESS,
            extracted_text="Some text",
            manual_review_required=False,
        )
        doc_id = upsert_syllabus_document(doc, "postgresql://fake/db")
        assert doc_id == "doc-uuid-1"

        # Verify the SQL contains ON CONFLICT
        sql, _ = mock_cur.execute.call_args[0]
        assert "ON CONFLICT" in sql


# ── Schema separation tests (offline) ────────────────────────────────────────


class TestSchemaSeparation:
    """Verify that observations are kept separate from catalog.courses."""

    def test_loader_insert_targets_syllabi_not_courses(self):
        from ingest.syllabus.loader import UPSERT_SQL
        assert "catalog.syllabi" in UPSERT_SQL
        # Loader must NOT write directly to catalog.courses
        assert "catalog.courses" not in UPSERT_SQL

    def test_migration_06_separates_observations_from_courses(self):
        sql = (MIGRATIONS_DIR / "06-syllabus-documents-and-observations.sql").read_text()
        # Observations table must be separate from courses
        assert "catalog.syllabus_observations" in sql
        assert "catalog.courses" not in sql.split("catalog.syllabus_observations")[0]  # not referenced before observations table


# ── Live DB tests (skipped unless DATABASE_URL is set) ───────────────────────


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set — skipping live DB tests")
class TestLiveMigrationAndUpsert:
    """Live Postgres tests for migration idempotency and upsert behavior.

    These tests require a running Postgres with DATABASE_URL set and all
    migrations already applied (init-db/migrate.py).

    Run with:
        DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \\
            python3 -m pytest ingest/syllabus/tests/test_db_integration.py -v -k live
    """

    def test_migrate_runner_is_idempotent(self):
        """Running migrate.py twice on a migrated DB must not raise."""
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "init-db/migrate.py"],
            capture_output=True,
            text=True,
            cwd=str(MIGRATIONS_DIR.parent),
            env={**os.environ, "DATABASE_URL": DATABASE_URL},
        )
        assert result.returncode == 0, (
            f"migrate.py failed on second run:\n{result.stdout}\n{result.stderr}"
        )

    def test_idempotent_upsert_does_not_duplicate_rows(self):
        """Inserting the same record twice leaves exactly one row in catalog.syllabi."""
        import psycopg2

        unique_url = f"https://api.hb2504.txst.edu/py/getsyllabus.py?class=LIVE_UPSERT_TEST"
        record = SyllabusRecord(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            section="UPSERT_TEST",
            semester="Fall 2024",
            semester_code="202510",
            instructor_name="Test Instructor",
            instructor_plid="xtest",
            source_url=unique_url,
            has_syllabus=True,
            original_format=None,
            syllabus_filename=None,
            credit_hours=4,
            index_num=99998,
            fetched_at=datetime.now(timezone.utc),
            catalog_year="2024-2025",
            source_host="api.hb2504.txst.edu",
        )

        # Insert first time
        load_records([record], DATABASE_URL)
        # Insert second time (must upsert, not duplicate)
        load_records([record], DATABASE_URL)

        # Verify exactly one row
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM catalog.syllabi WHERE source_url = %s",
                    (unique_url,),
                )
                count = cur.fetchone()[0]
        finally:
            conn.close()

        assert count == 1, f"Expected 1 row after idempotent upsert, found {count}"
