"""
tests/test_courses_endpoint.py — offline unit tests for the catalog-service.

All tests use FastAPI's TestClient with the database mocked out via
unittest.mock.patch, so no live Postgres instance is required.

Test coverage:
  1. Happy path: valid codes → matching CatalogResponse objects returned.
  2. Unknown codes omitted: code not in DB → not in response.
  3. 0 codes → 422.
  4. 21 codes → 422.
  5. /health → 200 {"status": "ok"}.
  6. /ready when DB is up → 200 {"status": "ready"}.
  7. /ready when DB is down → 503.
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
# Fixtures
# ---------------------------------------------------------------------------

# Sample DB rows: (course_code, course_name, prereq_tree, coreq_tree, requirements_parsed)
SAMPLE_ROW_CS3358 = (
    "CS3358",
    "Data Structures and Algorithms",
    {
        "kind": "all_of",
        "children": [
            {"kind": "course", "code": "CS1428", "min_grade": "C"},
            {"kind": "course", "code": "CS2318", "min_grade": "C"},
        ],
    },
    None,
    True,
)
SAMPLE_ROW_CS1428 = (
    "CS1428",
    "Beginning Programming",
    None,
    None,
    True,
)


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
# Tests
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
