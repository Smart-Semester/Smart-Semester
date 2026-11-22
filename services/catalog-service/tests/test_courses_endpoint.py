"""
tests/test_courses_endpoint.py — offline unit tests for the catalog-service.

All tests use FastAPI's TestClient with the database mocked out via
unittest.mock.patch, so no live Postgres instance is required.

Test coverage:
  Legacy (preserved):
  1.  Happy path: valid codes → matching CatalogResponse objects returned.
  2.  Unknown codes omitted: code not in DB → not in response.
  3.  0 codes → 422.
  4.  21 codes → 422.
  5.  /health → 200 {"status": "ok"}.
  6.  /ready when DB is up → 200 {"status": "ready"}.
  7.  /ready when DB is down → 503.

  Syllabus-document extension (new):
  8.  Canonical course with one document → syllabus_documents populated.
  9.  Canonical course with no documents → syllabus_documents: [].
  10. Canonical course with multiple documents → all returned, file_path absent.
  11. Syllabus-only course → title from syllabi, prereqs/coreqs null, requirements_parsed false.
  12. Unknown code (not in courses or syllabi) → omitted.
  13. Database error during courses query → 503.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# App bootstrap
# ---------------------------------------------------------------------------
# We import the app *after* patching the database pool so the lifespan does
# not try to connect to a real Postgres on startup.
# ---------------------------------------------------------------------------


def _make_mock_conn(rows: list[tuple]) -> MagicMock:
    """Return a mock psycopg2 connection that yields `rows` on fetchall()."""
    mock_cur = MagicMock()
    mock_cur.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = rows
    mock_cur.fetchone.return_value = rows[0] if rows else None

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cur
    return mock_conn


@contextmanager
def _mock_get_conn(rows: list[tuple]) -> Generator:
    yield _make_mock_conn(rows)


# ---------------------------------------------------------------------------
# Row shape helpers
# ---------------------------------------------------------------------------
# The new query returns 27 columns (indices 0–26).  Any column not relevant
# to a particular test fixture is set to a sensible sentinel/None.
#
# Column order (must stay in sync with courses.py _COL_* constants):
#  0  course_code
#  1  course_name
#  2  prereq_tree       (dict or None)
#  3  coreq_tree        (dict or None)
#  4  requirements_parsed
#  5  from_catalog      (bool — internal, not exposed)
#  6  document_id       (str UUID or None)
#  7  doc_source_url
#  8  content_type
#  9  original_filename
# 10  content_hash
# 11  file_size
# 12  download_status
# 13  extraction_status
# 14  extracted_text
# 15  page_count
# 16  character_count
# 17  manual_review_required
# 18  manual_review_reason
# 19  manual_review_notes
# 20  downloaded_at
# 21  extracted_at
# 22  semester
# 23  semester_code
# 24  section
# 25  instructor_name
# 26  has_syllabus

_NO_DOC = (None,) * 21  # columns 6–26 all NULL — no document row


def _course_no_doc(code: str, name: str, prereq=None, coreq=None, parsed=True):
    """Row for a canonical course with no syllabus document."""
    return (code, name, prereq, coreq, parsed, True) + _NO_DOC


def _course_with_doc(
    code: str,
    name: str,
    *,
    doc_id: str = "aaaaaaaa-0000-0000-0000-000000000001",
    source_url: str = "https://example.com/syllabus.pdf",
    content_type: str = "application/pdf",
    original_filename: str = "syllabus.pdf",
    content_hash: str = "abc123",
    file_size: int = 102400,
    download_status: str = "DOWNLOADED",
    extraction_status: str = "EXTRACTED",
    extracted_text: str = "Course introduction...",
    page_count: int = 5,
    character_count: int = 2000,
    manual_review_required: bool = False,
    manual_review_reason=None,
    manual_review_notes=None,
    downloaded_at=None,
    extracted_at=None,
    semester: str = "Fall 2024",
    semester_code: str = "202410",
    section: str = "001",
    instructor_name: str = "Dr. Smith",
    has_syllabus: bool = True,
    prereq=None,
    coreq=None,
    parsed: bool = True,
    from_catalog: bool = True,
):
    """Row for a canonical course joined to one syllabus document."""
    return (
        code, name, prereq, coreq, parsed, from_catalog,
        doc_id, source_url, content_type, original_filename,
        content_hash, file_size, download_status, extraction_status,
        extracted_text, page_count, character_count,
        manual_review_required, manual_review_reason, manual_review_notes,
        downloaded_at, extracted_at,
        semester, semester_code, section, instructor_name, has_syllabus,
    )


# ---------------------------------------------------------------------------
# Legacy fixtures (preserved — now 27-column shape)
# ---------------------------------------------------------------------------

SAMPLE_ROW_CS3358 = _course_with_doc(
    "CS3358",
    "Data Structures and Algorithms",
    prereq={
        "kind": "all_of",
        "children": [
            {"kind": "course", "code": "CS1428", "min_grade": "C"},
            {"kind": "course", "code": "CS2318", "min_grade": "C"},
        ],
    },
    parsed=True,
)

SAMPLE_ROW_CS1428 = _course_no_doc("CS1428", "Beginning Programming", parsed=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client_with_pool():
    """TestClient with the DB pool mocked so lifespan succeeds."""
    with patch("catalog_app.database._pool", new=MagicMock()):
        # Prevent lifespan from calling sys.exit or connecting to Postgres.
        with patch("catalog_app.database.init_pool", return_value=None):
            with patch("catalog_app.database.close_pool", return_value=None):
                # DATABASE_URL must be set so lifespan doesn't exit early.
                import os

                os.environ["DATABASE_URL"] = "postgresql://mock/mock"
                from catalog_app.main import app

                with TestClient(app, raise_server_exceptions=True) as c:
                    yield c


# ---------------------------------------------------------------------------
# Helper: patch get_conn for a specific set of rows
# ---------------------------------------------------------------------------


def _patch_get_conn(rows: list[tuple]):
    """Return a context-manager patch for catalog_app.database.get_conn."""
    return patch(
        "catalog_app.database.get_conn",
        side_effect=lambda: _mock_get_conn(rows),
    )


# ---------------------------------------------------------------------------
# Tests — legacy (preserved)
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_returns_ok(self, client_with_pool: TestClient) -> None:
        """GET /health → 200 {"status": "ok"}"""
        resp = client_with_pool.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestReady:
    def test_ready_when_db_up(self, client_with_pool: TestClient) -> None:
        """GET /ready when DB is up → 200 {"status": "ready"}"""
        with _patch_get_conn([(1,)]):
            resp = client_with_pool.get("/ready")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}

    def test_ready_when_db_down(self, client_with_pool: TestClient) -> None:
        """GET /ready when DB is down → 503"""
        with patch(
            "catalog_app.database.get_conn",
            side_effect=RuntimeError("connection refused"),
        ):
            resp = client_with_pool.get("/ready")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "unavailable"
        assert "detail" in body


class TestGetCourses:
    def test_happy_path_single_code(self, client_with_pool: TestClient) -> None:
        """Valid single code → matching CatalogResponse returned."""
        with _patch_get_conn([SAMPLE_ROW_CS3358]):
            resp = client_with_pool.get("/courses", params={"codes": "CS3358"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        course = data[0]
        assert course["code"] == "CS3358"
        assert course["title"] == "Data Structures and Algorithms"
        assert course["requirements_parsed"] is True
        assert course["coreqs"] is None
        assert course["prereqs"]["kind"] == "all_of"

    def test_happy_path_multiple_codes(self, client_with_pool: TestClient) -> None:
        """Valid multiple codes → all matching CatalogResponse objects returned."""
        with _patch_get_conn([SAMPLE_ROW_CS3358, SAMPLE_ROW_CS1428]):
            resp = client_with_pool.get(
                "/courses",
                params=[("codes", "CS3358"), ("codes", "CS1428")],
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        codes_returned = {c["code"] for c in data}
        assert codes_returned == {"CS3358", "CS1428"}

    def test_unknown_code_omitted(self, client_with_pool: TestClient) -> None:
        """Code not in DB → silently omitted (not a 404)."""
        # DB returns only CS1428, as if CS9999 is unknown.
        with _patch_get_conn([SAMPLE_ROW_CS1428]):
            resp = client_with_pool.get(
                "/courses",
                params=[("codes", "CS1428"), ("codes", "CS9999")],
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["code"] == "CS1428"

    def test_zero_codes_returns_422(self, client_with_pool: TestClient) -> None:
        """0 codes → 422 Unprocessable Entity."""
        resp = client_with_pool.get("/courses")
        assert resp.status_code == 422

    def test_twenty_one_codes_returns_422(self, client_with_pool: TestClient) -> None:
        """21 codes → 422 Unprocessable Entity."""
        params = [("codes", f"CS{1000 + i}") for i in range(21)]
        with _patch_get_conn([]):
            resp = client_with_pool.get("/courses", params=params)
        assert resp.status_code == 422

    def test_twenty_codes_accepted(self, client_with_pool: TestClient) -> None:
        """20 codes (the maximum) → accepted (200), not 422."""
        params = [("codes", f"CS{1000 + i}") for i in range(20)]
        with _patch_get_conn([]):
            resp = client_with_pool.get("/courses", params=params)
        assert resp.status_code == 200

    def test_no_prereqs_or_coreqs(self, client_with_pool: TestClient) -> None:
        """Course with null prereq_tree and coreq_tree → both null in response."""
        with _patch_get_conn([SAMPLE_ROW_CS1428]):
            resp = client_with_pool.get("/courses", params={"codes": "CS1428"})
        assert resp.status_code == 200
        course = resp.json()[0]
        assert course["prereqs"] is None
        assert course["coreqs"] is None
        assert course["requirements_parsed"] is True


class TestGetCoursesEdgeCases:
    """Section 7: boundary and error-path coverage for GET /courses."""

    def test_exactly_one_code_accepted(self, client_with_pool: TestClient) -> None:
        """1 code (the minimum) → accepted (200), not 422."""
        with _patch_get_conn([SAMPLE_ROW_CS1428]):
            resp = client_with_pool.get("/courses", params={"codes": "CS1428"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["code"] == "CS1428"

    def test_malformed_code_lowercase_returns_422(self, client_with_pool: TestClient) -> None:
        """Lowercase code → 422 (codes must be uppercase)."""
        resp = client_with_pool.get("/courses", params={"codes": "cs1428"})
        assert resp.status_code == 422

    def test_malformed_code_with_space_returns_422(self, client_with_pool: TestClient) -> None:
        """Code containing a space → 422."""
        resp = client_with_pool.get("/courses", params={"codes": "CS 1428"})
        assert resp.status_code == 422

    def test_mixed_valid_and_malformed_code_returns_422(self, client_with_pool: TestClient) -> None:
        """If any code is malformed, the entire request is rejected with 422."""
        params = [("codes", "CS3358"), ("codes", "cs1428")]
        resp = client_with_pool.get("/courses", params=params)
        assert resp.status_code == 422

    def test_database_failure_during_courses_query_returns_503(
        self, client_with_pool: TestClient
    ) -> None:
        """DB exception during GET /courses query → 503 Database unavailable."""
        from unittest.mock import patch
        with patch(
            "catalog_app.database.get_conn",
            side_effect=RuntimeError("pool exhausted"),
        ):
            resp = client_with_pool.get("/courses", params={"codes": "CS3358"})
        assert resp.status_code == 503

    def test_requirements_parsed_false_in_response(self, client_with_pool: TestClient) -> None:
        """requirements_parsed=False is faithfully returned when DB row has False."""
        row_unparsed = _course_no_doc("CS4321", "Some Course", parsed=False)
        with _patch_get_conn([row_unparsed]):
            resp = client_with_pool.get("/courses", params={"codes": "CS4321"})
        assert resp.status_code == 200
        course = resp.json()[0]
        assert course["requirements_parsed"] is False
        assert course["prereqs"] is None
        assert course["coreqs"] is None

    def test_all_twenty_codes_returned_when_all_known(self, client_with_pool: TestClient) -> None:
        """20 known codes → all 20 returned in response."""
        rows = [
            _course_no_doc(f"CS{1000 + i}", f"Course {i}", parsed=True)
            for i in range(20)
        ]
        params = [("codes", f"CS{1000 + i}") for i in range(20)]
        with _patch_get_conn(rows):
            resp = client_with_pool.get("/courses", params=params)
        assert resp.status_code == 200
        assert len(resp.json()) == 20


# ---------------------------------------------------------------------------
# Tests — syllabus_documents extension (new)
# ---------------------------------------------------------------------------


class TestSyllabusDocuments:
    """Coverage for the new syllabus_documents field on each CatalogResponse."""

    def test_canonical_course_with_one_document(self, client_with_pool: TestClient) -> None:
        """Canonical course joined to one document → syllabus_documents has 1 item."""
        row = _course_with_doc("CS3358", "Data Structures and Algorithms")
        with _patch_get_conn([row]):
            resp = client_with_pool.get("/courses", params={"codes": "CS3358"})
        assert resp.status_code == 200
        course = resp.json()[0]
        assert course["code"] == "CS3358"
        assert course["requirements_parsed"] is True
        assert isinstance(course["syllabus_documents"], list)
        assert len(course["syllabus_documents"]) == 1

        doc = course["syllabus_documents"][0]
        assert doc["document_id"] == "aaaaaaaa-0000-0000-0000-000000000001"
        assert doc["source_url"] == "https://example.com/syllabus.pdf"
        assert doc["content_type"] == "application/pdf"
        assert doc["original_filename"] == "syllabus.pdf"
        assert doc["content_hash"] == "abc123"
        assert doc["file_size"] == 102400
        assert doc["download_status"] == "DOWNLOADED"
        assert doc["extraction_status"] == "EXTRACTED"
        assert doc["extracted_text"] == "Course introduction..."
        assert doc["page_count"] == 5
        assert doc["character_count"] == 2000
        assert doc["manual_review_required"] is False
        assert doc["manual_review_reason"] is None
        assert doc["manual_review_notes"] is None
        assert doc["semester"] == "Fall 2024"
        assert doc["semester_code"] == "202410"
        assert doc["section"] == "001"
        assert doc["instructor_name"] == "Dr. Smith"
        assert doc["has_syllabus"] is True
        # file_path must NOT appear in the response
        assert "file_path" not in doc

    def test_canonical_course_with_no_documents(self, client_with_pool: TestClient) -> None:
        """Canonical course with no syllabus documents → syllabus_documents: []."""
        row = _course_no_doc("CS1428", "Beginning Programming", parsed=True)
        with _patch_get_conn([row]):
            resp = client_with_pool.get("/courses", params={"codes": "CS1428"})
        assert resp.status_code == 200
        course = resp.json()[0]
        assert course["code"] == "CS1428"
        assert course["syllabus_documents"] == []
        # Existing fields must still be present
        assert course["title"] == "Beginning Programming"
        assert course["requirements_parsed"] is True
        assert course["prereqs"] is None
        assert course["coreqs"] is None

    def test_canonical_course_with_multiple_documents(self, client_with_pool: TestClient) -> None:
        """Canonical course with two documents → both returned, no file_path exposed."""
        row1 = _course_with_doc(
            "CS3358",
            "Data Structures and Algorithms",
            doc_id="aaaaaaaa-0000-0000-0000-000000000001",
            source_url="https://example.com/s1.pdf",
            semester="Fall 2024",
            semester_code="202410",
            section="001",
        )
        row2 = _course_with_doc(
            "CS3358",
            "Data Structures and Algorithms",
            doc_id="bbbbbbbb-0000-0000-0000-000000000002",
            source_url="https://example.com/s2.pdf",
            semester="Spring 2025",
            semester_code="202510",
            section="002",
        )
        with _patch_get_conn([row1, row2]):
            resp = client_with_pool.get("/courses", params={"codes": "CS3358"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        course = data[0]
        assert len(course["syllabus_documents"]) == 2
        doc_ids = {d["document_id"] for d in course["syllabus_documents"]}
        assert doc_ids == {
            "aaaaaaaa-0000-0000-0000-000000000001",
            "bbbbbbbb-0000-0000-0000-000000000002",
        }
        for doc in course["syllabus_documents"]:
            assert "file_path" not in doc

    def test_syllabus_only_course(self, client_with_pool: TestClient) -> None:
        """Code found only in catalog.syllabi → title from syllabi, prereqs/coreqs null, parsed=false."""
        row = _course_with_doc(
            "HIST1310",
            "United States History I",
            prereq=None,
            coreq=None,
            parsed=False,
            from_catalog=False,  # signals it came from the syllabus-only branch
        )
        with _patch_get_conn([row]):
            resp = client_with_pool.get("/courses", params={"codes": "HIST1310"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        course = data[0]
        assert course["code"] == "HIST1310"
        assert course["title"] == "United States History I"
        assert course["prereqs"] is None
        assert course["coreqs"] is None
        assert course["requirements_parsed"] is False
        assert len(course["syllabus_documents"]) == 1

    def test_unknown_code_not_in_courses_or_syllabi(self, client_with_pool: TestClient) -> None:
        """Code not in catalog.courses OR catalog.syllabi → omitted silently."""
        # DB returns empty — no rows match CS9999
        with _patch_get_conn([]):
            resp = client_with_pool.get("/courses", params={"codes": "CS9999"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_database_error_returns_503(self, client_with_pool: TestClient) -> None:
        """Any DB exception → 503 with 'Database unavailable.' detail."""
        with patch(
            "catalog_app.database.get_conn",
            side_effect=Exception("unexpected DB failure"),
        ):
            resp = client_with_pool.get("/courses", params={"codes": "CS3358"})
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Database unavailable."

    def test_file_path_never_exposed(self, client_with_pool: TestClient) -> None:
        """file_path column must never appear in any syllabus_documents item."""
        row = _course_with_doc("CS1428", "Beginning Programming")
        with _patch_get_conn([row]):
            resp = client_with_pool.get("/courses", params={"codes": "CS1428"})
        assert resp.status_code == 200
        for course in resp.json():
            for doc in course.get("syllabus_documents", []):
                assert "file_path" not in doc

    def test_manual_review_fields_populated(self, client_with_pool: TestClient) -> None:
        """manual_review_required=True documents expose reason and notes."""
        row = _course_with_doc(
            "CS2318",
            "Assembly Language",
            manual_review_required=True,
            manual_review_reason="SCANNED_DOCUMENT",
            manual_review_notes="Needs OCR",
        )
        with _patch_get_conn([row]):
            resp = client_with_pool.get("/courses", params={"codes": "CS2318"})
        assert resp.status_code == 200
        doc = resp.json()[0]["syllabus_documents"][0]
        assert doc["manual_review_required"] is True
        assert doc["manual_review_reason"] == "SCANNED_DOCUMENT"
        assert doc["manual_review_notes"] == "Needs OCR"

    def test_syllabus_documents_field_always_present(self, client_with_pool: TestClient) -> None:
        """Every CatalogResponse must include syllabus_documents, even if empty."""
        rows = [
            _course_no_doc(f"CS{1000 + i}", f"Course {i}", parsed=True)
            for i in range(3)
        ]
        params = [("codes", f"CS{1000 + i}") for i in range(3)]
        with _patch_get_conn(rows):
            resp = client_with_pool.get("/courses", params=params)
        assert resp.status_code == 200
        for course in resp.json():
            assert "syllabus_documents" in course
            assert isinstance(course["syllabus_documents"], list)
