"""Tests for planner-service schemas.

Covers:
  - RequirementNode discriminated-union parsing
  - AllOfNode / AnyOfNode empty-children validation (2d)
  - CatalogResponse.requirements_parsed semantics (2e)
  - Round-trip serialization of nested trees
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import (
    AllOfNode,
    AnyOfNode,
    CatalogResponse,
    CourseNode,
    ManualNode,
    RequirementNode,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def course(code: str, min_grade: str = "C") -> dict:
    return {"kind": "course", "code": code, "min_grade": min_grade}

def all_of(*children: dict) -> dict:
    return {"kind": "all_of", "children": list(children)}

def any_of(*children: dict) -> dict:
    return {"kind": "any_of", "children": list(children)}

def manual(text: str) -> dict:
    return {"kind": "manual", "requirements": text}


# ── Node parsing ───────────────────────────────────────────────────────────────

class TestCourseNode:
    def test_valid_course_node(self):
        node = CourseNode(**course("CS1428", "C"))
        assert node.kind == "course"
        assert node.code == "CS1428"
        assert node.min_grade == "C"

    def test_all_valid_min_grades(self):
        for grade in ("A", "B", "C", "D"):
            node = CourseNode(**course("CS1428", grade))
            assert node.min_grade == grade

    def test_invalid_min_grade_f(self):
        with pytest.raises(ValidationError):
            CourseNode(**course("CS1428", "F"))  # F is not a valid min_grade

    def test_invalid_min_grade_ip(self):
        with pytest.raises(ValidationError):
            CourseNode(**course("CS1428", "IP"))


class TestAllOfNode:
    def test_valid_all_of(self):
        node = AllOfNode(**all_of(course("CS1428"), course("CS2318")))
        assert node.kind == "all_of"
        assert len(node.children) == 2

    def test_single_child_is_valid(self):
        node = AllOfNode(**all_of(course("CS1428")))
        assert len(node.children) == 1

    def test_empty_children_raises(self):
        """Decision 2d: all_of with no children is invalid."""
        with pytest.raises(ValidationError, match="all_of node must have at least one child"):
            AllOfNode(kind="all_of", children=[])

    def test_nested_any_of_inside_all_of(self):
        node = AllOfNode(**all_of(
            course("CS1428"),
            any_of(course("PHIL1305"), course("COMM1315")),
        ))
        assert len(node.children) == 2
        assert node.children[1].kind == "any_of"


class TestAnyOfNode:
    def test_valid_any_of(self):
        node = AnyOfNode(**any_of(course("PHIL1305"), course("COMM1315")))
        assert node.kind == "any_of"
        assert len(node.children) == 2

    def test_single_child_is_valid(self):
        node = AnyOfNode(**any_of(course("CS1428")))
        assert len(node.children) == 1

    def test_empty_children_raises(self):
        """Decision 2d: any_of with no children is invalid."""
        with pytest.raises(ValidationError, match="any_of node must have at least one child"):
            AnyOfNode(kind="any_of", children=[])


class TestManualNode:
    def test_valid_manual(self):
        node = ManualNode(**manual("Instructor consent required."))
        assert node.kind == "manual"
        assert node.requirements == "Instructor consent required."


# ── CatalogResponse ────────────────────────────────────────────────────────────

class TestCatalogResponse:
    def test_no_requirements_parsed_true(self):
        """Decision 2e: parsed=True + null prereqs means genuinely no prereqs."""
        resp = CatalogResponse(
            code="CS1101",
            title="Intro",
            prereqs=None,
            coreqs=None,
            requirements_parsed=True,
        )
        assert resp.requirements_parsed is True
        assert resp.prereqs is None

    def test_not_yet_parsed_is_default(self):
        """Decision 2e: requirements_parsed defaults to False."""
        resp = CatalogResponse(code="CS1101", title="Intro")
        assert resp.requirements_parsed is False

    def test_parsed_false_with_null_means_unknown(self):
        """False + null prereqs = not yet parsed, NOT 'no requirements'."""
        resp = CatalogResponse(
            code="CS9999",
            title="Unparsed Course",
            requirements_parsed=False,
        )
        assert resp.requirements_parsed is False
        assert resp.prereqs is None

    def test_full_tree_with_parsed_true(self):
        """Complex nested tree round-trips through CatalogResponse correctly."""
        payload = {
            "code": "CS3358",
            "title": "Data Structures and Algorithms",
            "requirements_parsed": True,
            "prereqs": all_of(
                course("CS1428", "C"),
                course("CS2318", "C"),
                any_of(course("PHIL1305", "D"), course("COMM1315", "D")),
            ),
            "coreqs": None,
        }
        resp = CatalogResponse(**payload)
        assert resp.code == "CS3358"
        assert resp.requirements_parsed is True
        assert resp.prereqs is not None
        assert resp.prereqs.kind == "all_of"
        assert len(resp.prereqs.children) == 3
        nested = resp.prereqs.children[2]
        assert nested.kind == "any_of"
        assert len(nested.children) == 2

    def test_manual_prereq(self):
        resp = CatalogResponse(
            code="CS4999",
            title="Special Topics",
            requirements_parsed=True,
            prereqs={"kind": "manual", "requirements": "Instructor consent required."},
        )
        assert resp.prereqs.kind == "manual"

    def test_coreqs_can_be_tree(self):
        resp = CatalogResponse(
            code="CS3358",
            title="DSA",
            requirements_parsed=True,
            coreqs=course("MATH2471", "D"),
        )
        assert resp.coreqs.kind == "course"
        assert resp.coreqs.code == "MATH2471"

    def test_serialization_includes_requirements_parsed(self):
        """requirements_parsed appears in the serialized output."""
        resp = CatalogResponse(
            code="CS1428", title="Intro", requirements_parsed=True
        )
        data = resp.model_dump()
        assert "requirements_parsed" in data
        assert data["requirements_parsed"] is True

    def test_empty_all_of_rejected_inside_catalog_response(self):
        """The empty-children guard fires even when nested inside CatalogResponse."""
        with pytest.raises(ValidationError):
            CatalogResponse(
                code="CS1428",
                title="Intro",
                requirements_parsed=True,
                prereqs={"kind": "all_of", "children": []},
            )

    def test_empty_any_of_rejected_inside_catalog_response(self):
        with pytest.raises(ValidationError):
            CatalogResponse(
                code="CS1428",
                title="Intro",
                requirements_parsed=True,
                prereqs={"kind": "any_of", "children": []},
            )
