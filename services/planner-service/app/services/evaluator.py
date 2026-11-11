"""Eligibility evaluator — pure logic, no network or DB access.

evaluate() takes a list of planned course codes, the catalog data for those
codes, and the student's completed courses, and returns a CourseResponse for
each planned code in the same order.

Grade ordering (highest to lowest): A > B > C > D.
A completed course satisfies a CourseNode when:
  - the course code matches, AND
  - the student's grade is >= the node's min_grade.
"""
from __future__ import annotations

from typing import List, Optional

from app.schemas import (
    AllOfNode,
    AnyOfNode,
    CatalogResponse,
    CompletedCourse,
    CourseNode,
    CourseResponse,
    CourseStatus,
    ManualNode,
    RequirementNode,
)

# Grade order (index 0 is the highest passing grade)
_GRADE_ORDER: List[str] = ["A", "B", "C", "D"]


def _grade_gte(achieved: str, required: str) -> bool:
    """Return True when *achieved* grade is >= *required* grade."""
    # Non-passing grades (F, IP, W) can never satisfy a prerequisite.
    if achieved not in _GRADE_ORDER or required not in _GRADE_ORDER:
        return False
    return _GRADE_ORDER.index(achieved) <= _GRADE_ORDER.index(required)


def _build_grade_map(completed: List[CompletedCourse]) -> dict[str, str]:
    """Return {course_code: best_grade} from the completed-courses list.

    When a student has taken the same course multiple times, keep the best grade.
    """
    grade_map: dict[str, str] = {}
    for c in completed:
        code = c.code
        if code not in grade_map:
            grade_map[code] = c.grade
        else:
            # Keep the better grade
            prev = grade_map[code]
            if prev in _GRADE_ORDER and c.grade in _GRADE_ORDER:
                if _GRADE_ORDER.index(c.grade) < _GRADE_ORDER.index(prev):
                    grade_map[code] = c.grade
            elif c.grade in _GRADE_ORDER:
                grade_map[code] = c.grade
    return grade_map


class _EvalResult:
    """Internal result of evaluating a single requirement node."""

    __slots__ = ("met", "unmet_node", "manual_text")

    def __init__(
        self,
        met: bool,
        unmet_node: Optional[RequirementNode] = None,
        manual_text: Optional[str] = None,
    ) -> None:
        self.met = met
        # The subtree of unmet requirements (returned in CourseResponse)
        self.unmet_node = unmet_node
        # Non-None when a ManualNode was encountered anywhere in the tree
        self.manual_text = manual_text


def _eval_node(node: RequirementNode, grade_map: dict[str, str]) -> _EvalResult:
    """Recursively evaluate a requirement node."""

    if isinstance(node, CourseNode):
        achieved = grade_map.get(node.code)
        if achieved is not None and _grade_gte(achieved, node.min_grade):
            return _EvalResult(met=True)
        return _EvalResult(met=False, unmet_node=node)

    if isinstance(node, ManualNode):
        return _EvalResult(met=False, unmet_node=node, manual_text=node.requirements)

    if isinstance(node, AllOfNode):
        # ALL children must be met
        unmet_children: List[RequirementNode] = []
        manual_text: Optional[str] = None
        for child in node.children:
            result = _eval_node(child, grade_map)
            if result.manual_text:
                manual_text = result.manual_text
            if not result.met:
                if result.unmet_node is not None:
                    unmet_children.append(result.unmet_node)
        if not unmet_children and manual_text is None:
            return _EvalResult(met=True)
        # Build the unmet subtree
        if len(unmet_children) == 1:
            unmet = unmet_children[0]
        elif len(unmet_children) > 1:
            unmet = AllOfNode(kind="all_of", children=unmet_children)
        else:
            # Only manual failure — node itself is unmet
            unmet = node
        return _EvalResult(met=False, unmet_node=unmet, manual_text=manual_text)

    if isinstance(node, AnyOfNode):
        # AT LEAST ONE child must be met
        unmet_children = []
        manual_text = None
        for child in node.children:
            result = _eval_node(child, grade_map)
            if result.manual_text:
                manual_text = result.manual_text
            if result.met:
                return _EvalResult(met=True)
            if result.unmet_node is not None:
                unmet_children.append(result.unmet_node)
        # None of the children were met
        if len(unmet_children) == 1:
            unmet = unmet_children[0]
        elif len(unmet_children) > 1:
            unmet = AnyOfNode(kind="any_of", children=unmet_children)
        else:
            unmet = node
        return _EvalResult(met=False, unmet_node=unmet, manual_text=manual_text)

    # Unreachable — unknown node kind
    return _EvalResult(met=False, unmet_node=node)


def evaluate(
    planned_codes: List[str],
    catalog_map: dict[str, CatalogResponse],
    completed_courses: List[CompletedCourse],
) -> List[CourseResponse]:
    """Evaluate eligibility for each planned course code.

    Returns a list of CourseResponse objects in the same order as
    *planned_codes*.
    """
    grade_map = _build_grade_map(completed_courses)
    responses: List[CourseResponse] = []

    for code in planned_codes:
        if code not in catalog_map:
            responses.append(
                CourseResponse(code=code, status=CourseStatus.UNKNOWN_COURSE)
            )
            continue

        catalog_entry = catalog_map[code]

        if not catalog_entry.requirements_parsed:
            responses.append(
                CourseResponse(
                    code=code,
                    status=CourseStatus.CANNOT_VERIFY,
                    status_description="Requirements not yet parsed for this course",
                )
            )
            continue

        # Evaluate prereqs and coreqs
        prereq_result: Optional[_EvalResult] = None
        coreq_result: Optional[_EvalResult] = None

        if catalog_entry.prereqs is not None:
            prereq_result = _eval_node(catalog_entry.prereqs, grade_map)

        if catalog_entry.coreqs is not None:
            coreq_result = _eval_node(catalog_entry.coreqs, grade_map)

        # Check for any manual node anywhere in the trees
        manual_text: Optional[str] = None
        if prereq_result and prereq_result.manual_text:
            manual_text = prereq_result.manual_text
        if coreq_result and coreq_result.manual_text:
            manual_text = coreq_result.manual_text

        if manual_text is not None:
            responses.append(
                CourseResponse(
                    code=code,
                    status=CourseStatus.CANNOT_VERIFY,
                    status_description=manual_text,
                )
            )
            continue

        prereqs_met = prereq_result is None or prereq_result.met
        coreqs_met = coreq_result is None or coreq_result.met

        if prereqs_met and coreqs_met:
            responses.append(CourseResponse(code=code, status=CourseStatus.ELIGIBLE))
        else:
            responses.append(
                CourseResponse(
                    code=code,
                    status=CourseStatus.NOT_ELIGIBLE,
                    unmet_prereqs=(
                        prereq_result.unmet_node
                        if prereq_result and not prereq_result.met
                        else None
                    ),
                    unmet_coreqs=(
                        coreq_result.unmet_node
                        if coreq_result and not coreq_result.met
                        else None
                    ),
                )
            )

    return responses
