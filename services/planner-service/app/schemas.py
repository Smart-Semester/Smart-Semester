from pydantic import BaseModel, Field, model_validator
from typing import List, Union, Literal, Annotated
from enum import Enum

# eligibility request and result are in their completed form.
# CatalogResponse is the agreed contract shape — see docs/Catalog-API-Contract.md.

# ── Eligibility request ───────────────────────────────────────────────────────

class CompletedCourse(BaseModel):
    code: str
    grade: Literal["A", "B", "C", "D", "F", "IP", "W"]

class EligibilityRequest(BaseModel):
    planned_codes: List[str]
    completed_courses: List[CompletedCourse] = Field(default_factory=list)

# JSON example for a catalog response (from Catalog-API-Contract.md):
# this is not final and is dependent on the catalog service
# implementation
# {
#   "code": "CS3358",
#   "title": "Data Structures and Algorithms",
#   "prereqs": {
#     "kind": "all_of",
#     "children": [
#       { "kind": "course", "code": "CS1428", "min_grade": "C" },
#       { "kind": "course", "code": "CS2318", "min_grade": "C" },
#       {
#         "kind": "any_of",
#         "children": [
#           { "kind": "course", "code": "PHIL1305", "min_grade": "D" },
#           { "kind": "course", "code": "COMM1315", "min_grade": "D" }
#         ]
#       }
#     ]
#   },
#   "coreqs": null,
#   "requirements_parsed": true
# }

# ── Requirement tree nodes ────────────────────────────────────────────────────
#
# Node kinds:
#   course  — a single course with a minimum passing grade
#   all_of  — ALL children must be satisfied (AND)
#   any_of  — AT LEAST ONE child must be satisfied (OR)
#   manual  — free-text requirement (consent, standing, etc.)
#
# Contract rule: null means "no requirement". An all_of/any_of with zero
# children is never valid — the catalog parser must produce null instead.
class CourseNode(BaseModel):
    kind: Literal["course"] = "course"
    code: str
    min_grade: Literal["A", "B", "C", "D"]

class AllOfNode(BaseModel):
    kind: Literal["all_of"] = "all_of"
    children: List["RequirementNode"]

    @model_validator(mode="after")
    def children_must_not_be_empty(self) -> "AllOfNode":
        if not self.children:
            raise ValueError(
                "all_of node must have at least one child. "
                "Use null at the prereqs/coreqs level to represent no requirements."
            )
        return self

class AnyOfNode(BaseModel):
    kind: Literal["any_of"] = "any_of"
    children: List["RequirementNode"]

    @model_validator(mode="after")
    def children_must_not_be_empty(self) -> "AnyOfNode":
        if not self.children:
            raise ValueError(
                "any_of node must have at least one child. "
                "Use null at the prereqs/coreqs level to represent no requirements."
            )
        return self

class ManualNode(BaseModel):
    kind: Literal["manual"] = "manual"
    requirements: str

# builds a tree structure using the above nodes to define prereqs/coreqs.
# Discriminated union — Pydantic picks the right model from the "kind" field.
RequirementNode = Annotated[Union[CourseNode, AllOfNode, AnyOfNode, ManualNode], Field(discriminator="kind")]
# rebuilds now that RequirementNode is defined
AllOfNode.model_rebuild()
AnyOfNode.model_rebuild()

# ── Catalog response ──────────────────────────────────────────────────────────

class CatalogResponse(BaseModel):
    code: str
    title: str
    prereqs: RequirementNode | None = None
    coreqs: RequirementNode | None = None
    requirements_parsed: bool = False
    # requirements_parsed distinguishes two states that both produce null prereqs/coreqs:
    #   False → requirements have NOT been parsed yet (raw text may exist in DB)
    #   True  → requirements were parsed; null means the course genuinely has none
    # The planner must treat False as "requirements unknown", not "no requirements".

# ── Eligibility response ──────────────────────────────────────────────────────

# defines the response to an eligibility check
class CourseStatus(str, Enum):
    ELIGIBLE = 'eligible'
    NOT_ELIGIBLE = 'not_eligible'
    CANNOT_VERIFY = 'cannot_verify'
    UNKNOWN_COURSE = 'unknown_course'

class CourseResponse(BaseModel):
    status: CourseStatus
    status_description: str | None = None  # explains cannot_verify errors
    code: str
    unmet_prereqs: RequirementNode | None = None
    unmet_coreqs: RequirementNode | None = None

class EligibilityResponse(BaseModel):
    results: List[CourseResponse] = Field(default_factory=list)
