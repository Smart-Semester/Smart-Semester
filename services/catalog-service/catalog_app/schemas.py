from __future__ import annotations

from pydantic import BaseModel, Field, model_validator
from typing import List, Union, Literal, Annotated, Optional


# ── Requirement tree nodes ────────────────────────────────────────────────────
#
# Mirrors the shapes in planner-service/app/schemas.py exactly so that JSON
# produced here can be directly consumed by the planner without translation.
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


# Discriminated union — Pydantic picks the right model from the "kind" field.
RequirementNode = Annotated[
    Union[CourseNode, AllOfNode, AnyOfNode, ManualNode],
    Field(discriminator="kind"),
]

# Rebuild forward references now that RequirementNode is defined.
AllOfNode.model_rebuild()
AnyOfNode.model_rebuild()


# ── Catalog response (the external API shape) ─────────────────────────────────


class CatalogResponse(BaseModel):
    code: str
    title: str
    prereqs: Optional[RequirementNode] = None
    coreqs: Optional[RequirementNode] = None
    requirements_parsed: bool = False
    # requirements_parsed distinguishes two states that both produce null
    # prereqs/coreqs:
    #   False → requirements have NOT been parsed yet (raw text may exist in DB)
    #   True  → requirements were parsed; null means the course genuinely has none
    # The planner must treat False as "requirements unknown", not "no requirements".


# ── Internal DB model (not exposed in the API) ────────────────────────────────


class CourseRow(BaseModel):
    """Raw row returned from catalog.courses — used internally before mapping."""

    course_code: str
    course_name: str
    prereq_tree: Optional[dict] = None   # JSONB, already a dict from psycopg2
    coreq_tree: Optional[dict] = None    # JSONB, already a dict from psycopg2
    requirements_parsed: bool = False

    def to_catalog_response(self) -> CatalogResponse:
        """Convert a DB row to the public CatalogResponse shape."""
        from pydantic import TypeAdapter

        node_adapter: TypeAdapter[Optional[RequirementNode]] = TypeAdapter(
            Optional[RequirementNode]
        )

        prereqs = node_adapter.validate_python(self.prereq_tree) if self.prereq_tree else None
        coreqs = node_adapter.validate_python(self.coreq_tree) if self.coreq_tree else None

        return CatalogResponse(
            code=self.course_code,
            title=self.course_name,
            prereqs=prereqs,
            coreqs=coreqs,
            requirements_parsed=self.requirements_parsed,
        )
