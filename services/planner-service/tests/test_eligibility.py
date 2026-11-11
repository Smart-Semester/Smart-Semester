"""Offline tests for planner-service eligibility flow and evaluator logic.

No live Catalog service or DB is required.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.clients.catalog import CatalogClient, CatalogUnavailableError
from app.main import app
from app.schemas import (
    AllOfNode,
    AnyOfNode,
    CatalogResponse,
    CompletedCourse,
    CourseNode,
    CourseResponse,
    CourseStatus,
    EligibilityRequest,
    ManualNode,
)
from app.services import evaluator


# ── Helpers for test fixtures ──────────────────────────────────────────────────

def c_node(code: str, min_grade: str = "C") -> CourseNode:
    return CourseNode(kind="course", code=code, min_grade=min_grade)


def all_of_nodes(*children) -> AllOfNode:
    return AllOfNode(kind="all_of", children=list(children))


def any_of_nodes(*children) -> AnyOfNode:
    return AnyOfNode(kind="any_of", children=list(children))


def manual_node(text: str) -> ManualNode:
    return ManualNode(kind="manual", requirements=text)


# ── Unit tests for evaluator.evaluate() ───────────────────────────────────────

class TestEvaluatorPureLogic:
    def test_single_prereq_satisfied(self):
        catalog_map = {
            "CS2308": CatalogResponse(
                code="CS2308",
                title="Foundations II",
                prereqs=c_node("CS1428", "C"),
                requirements_parsed=True,
            )
        }
        completed = [CompletedCourse(code="CS1428", grade="B")]
        res = evaluator.evaluate(["CS2308"], catalog_map, completed)

        assert len(res) == 1
        assert res[0].code == "CS2308"
        assert res[0].status == CourseStatus.ELIGIBLE
        assert res[0].unmet_prereqs is None

    def test_single_prereq_not_satisfied_due_to_low_grade(self):
        catalog_map = {
            "CS2308": CatalogResponse(
                code="CS2308",
                title="Foundations II",
                prereqs=c_node("CS1428", "C"),
                requirements_parsed=True,
            )
        }
        completed = [CompletedCourse(code="CS1428", grade="D")]
        res = evaluator.evaluate(["CS2308"], catalog_map, completed)

        assert len(res) == 1
        assert res[0].code == "CS2308"
        assert res[0].status == CourseStatus.NOT_ELIGIBLE
        assert res[0].unmet_prereqs is not None
        assert res[0].unmet_prereqs.kind == "course"

    def test_single_prereq_not_taken(self):
        catalog_map = {
            "CS2308": CatalogResponse(
                code="CS2308",
                title="Foundations II",
                prereqs=c_node("CS1428", "C"),
                requirements_parsed=True,
            )
        }
        completed = []
        res = evaluator.evaluate(["CS2308"], catalog_map, completed)

        assert len(res) == 1
        assert res[0].status == CourseStatus.NOT_ELIGIBLE
        assert res[0].unmet_prereqs is not None

    def test_repeated_course_keeps_best_grade(self):
        catalog_map = {
            "CS2308": CatalogResponse(
                code="CS2308",
                title="Foundations II",
                prereqs=c_node("CS1428", "C"),
                requirements_parsed=True,
            )
        }
        # Student took CS1428 twice: first D, then A
        completed = [
            CompletedCourse(code="CS1428", grade="D"),
            CompletedCourse(code="CS1428", grade="A"),
        ]
        res = evaluator.evaluate(["CS2308"], catalog_map, completed)
        assert res[0].status == CourseStatus.ELIGIBLE

    def test_all_of_prereqs_all_met(self):
        catalog_map = {
            "CS3358": CatalogResponse(
                code="CS3358",
                title="Data Structures",
                prereqs=all_of_nodes(c_node("CS1428", "C"), c_node("CS2318", "C")),
                requirements_parsed=True,
            )
        }
        completed = [
            CompletedCourse(code="CS1428", grade="C"),
            CompletedCourse(code="CS2318", grade="B"),
        ]
        res = evaluator.evaluate(["CS3358"], catalog_map, completed)
        assert res[0].status == CourseStatus.ELIGIBLE

    def test_all_of_prereqs_one_unmet(self):
        catalog_map = {
            "CS3358": CatalogResponse(
                code="CS3358",
                title="Data Structures",
                prereqs=all_of_nodes(c_node("CS1428", "C"), c_node("CS2318", "C")),
                requirements_parsed=True,
            )
        }
        completed = [CompletedCourse(code="CS1428", grade="C")]
        res = evaluator.evaluate(["CS3358"], catalog_map, completed)
        assert res[0].status == CourseStatus.NOT_ELIGIBLE
        assert res[0].unmet_prereqs is not None
        assert res[0].unmet_prereqs.kind == "course"
        assert res[0].unmet_prereqs.code == "CS2318"

    def test_any_of_prereqs_one_met_satisfies(self):
        catalog_map = {
            "CS4328": CatalogResponse(
                code="CS4328",
                title="Operating Systems",
                prereqs=any_of_nodes(c_node("CS3358", "C"), c_node("EE3358", "C")),
                requirements_parsed=True,
            )
        }
        completed = [CompletedCourse(code="EE3358", grade="C")]
        res = evaluator.evaluate(["CS4328"], catalog_map, completed)
        assert res[0].status == CourseStatus.ELIGIBLE

    def test_any_of_prereqs_none_met(self):
        catalog_map = {
            "CS4328": CatalogResponse(
                code="CS4328",
                title="Operating Systems",
                prereqs=any_of_nodes(c_node("CS3358", "C"), c_node("EE3358", "C")),
                requirements_parsed=True,
            )
        }
        completed = [CompletedCourse(code="MATH2471", grade="A")]
        res = evaluator.evaluate(["CS4328"], catalog_map, completed)
        assert res[0].status == CourseStatus.NOT_ELIGIBLE
        assert res[0].unmet_prereqs is not None

    def test_manual_requirement_causes_cannot_verify(self):
        catalog_map = {
            "CS4398": CatalogResponse(
                code="CS4398",
                title="Senior Project",
                prereqs=manual_node("Departmental approval required"),
                requirements_parsed=True,
            )
        }
        res = evaluator.evaluate(["CS4398"], catalog_map, [])
        assert res[0].status == CourseStatus.CANNOT_VERIFY
        assert "Departmental approval" in (res[0].status_description or "")

    def test_unparsed_requirements_causes_cannot_verify(self):
        catalog_map = {
            "CS1308": CatalogResponse(
                code="CS1308",
                title="Intro to CS",
                prereqs=None,
                requirements_parsed=False,
            )
        }
        res = evaluator.evaluate(["CS1308"], catalog_map, [])
        assert res[0].status == CourseStatus.CANNOT_VERIFY
        assert "not yet parsed" in (res[0].status_description or "")

    def test_unknown_course_status(self):
        catalog_map = {}  # empty catalog
        res = evaluator.evaluate(["UNKNOWN101"], catalog_map, [])
        assert res[0].status == CourseStatus.UNKNOWN_COURSE

    def test_coreq_unmet_causes_not_eligible(self):
        catalog_map = {
            "CS1428": CatalogResponse(
                code="CS1428",
                title="Foundations I",
                prereqs=None,
                coreqs=c_node("MATH1315", "C"),
                requirements_parsed=True,
            )
        }
        res = evaluator.evaluate(["CS1428"], catalog_map, [])
        assert res[0].status == CourseStatus.NOT_ELIGIBLE
        assert res[0].unmet_coreqs is not None


# ── Unit tests for CatalogClient batching & error handling ────────────────────

class TestCatalogClient:
    def test_batches_split_over_twenty(self):
        codes = [f"CS{1000 + i}" for i in range(25)]
        batches = list(CatalogClient._batches(codes))
        assert len(batches) == 2
        assert len(batches[0]) == 20
        assert len(batches[1]) == 5

    @patch("urllib.request.urlopen")
    def test_get_courses_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = json.dumps([
            {"code": "CS1428", "title": "Foundations I", "requirements_parsed": True}
        ]).encode()
        mock_urlopen.return_value = mock_resp

        client = CatalogClient("http://catalog:8001")
        courses = client.get_courses(["CS1428"])
        assert len(courses) == 1
        assert courses[0].code == "CS1428"

    @patch("urllib.request.urlopen")
    def test_get_courses_outage_raises_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        client = CatalogClient("http://catalog:8001")
        with pytest.raises(CatalogUnavailableError, match="Catalog service unavailable"):
            client.get_courses(["CS1428"])


# ── Integration tests for POST /eligibility/checks router ─────────────────────

class TestEligibilityRouter:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    @patch.object(CatalogClient, "get_courses")
    def test_eligibility_checks_happy_path(self, mock_get_courses, client: TestClient):
        mock_get_courses.return_value = [
            CatalogResponse(
                code="CS2308",
                title="Foundations II",
                prereqs=c_node("CS1428", "C"),
                requirements_parsed=True,
            )
        ]

        payload = {
            "planned_codes": ["cs2308"],  # test lowercase normalization
            "completed_courses": [{"code": "CS1428", "grade": "B"}],
        }
        resp = client.post("/eligibility/checks", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["code"] == "CS2308"
        assert data["results"][0]["status"] == "eligible"

    @patch.object(CatalogClient, "get_courses")
    def test_eligibility_checks_catalog_outage_returns_503(
        self, mock_get_courses, client: TestClient
    ):
        mock_get_courses.side_effect = CatalogUnavailableError("connection error")

        payload = {
            "planned_codes": ["CS2308"],
            "completed_courses": [],
        }
        resp = client.post("/eligibility/checks", json=payload)
        assert resp.status_code == 503
        assert "Catalog service unavailable" in resp.json()["detail"]

    @patch.object(CatalogClient, "get_courses")
    def test_eligibility_checks_unknown_course(
        self, mock_get_courses, client: TestClient
    ):
        mock_get_courses.return_value = []  # Catalog found nothing

        payload = {
            "planned_codes": ["CS9999"],
            "completed_courses": [],
        }
        resp = client.post("/eligibility/checks", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"][0]["status"] == "unknown_course"
