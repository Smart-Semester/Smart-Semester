"""
courses.py — GET /courses router.

Spec (from docs/Catalog-API-Contract.md):
  GET /courses?codes=CS3358&codes=CS1428
  - `codes` is repeatable; 1–20 codes required; 422 if 0 or >20.
  - Codes must be uppercase with no spaces.
  - Unknown codes are silently omitted.
  - Returns a JSON array of CatalogResponse objects.
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query

from catalog_app import database
from catalog_app.schemas import CatalogResponse, CourseRow

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_CODES = 20
_QUERY = (
    "SELECT course_code, course_name, prereq_tree, coreq_tree, requirements_parsed "
    "FROM catalog.courses "
    "WHERE course_code = ANY(%s)"
)


EXAMPLE_CATALOG_RESPONSE = [
    {
        "code": "CS3358",
        "title": "Data Structures and Algorithms",
        "requirements_parsed": True,
        "prereqs": {
            "kind": "all_of",
            "children": [
                {"kind": "course", "code": "CS1428", "min_grade": "C"},
                {"kind": "course", "code": "CS2318", "min_grade": "C"},
                {
                    "kind": "any_of",
                    "children": [
                        {"kind": "course", "code": "PHIL1305", "min_grade": "D"},
                        {"kind": "course", "code": "COMM1315", "min_grade": "D"},
                    ],
                },
            ],
        },
        "coreqs": None,
    }
]


@router.get(
    "/courses",
    response_model=List[CatalogResponse],
    summary="Fetch course catalog entries",
    description=(
        "Return catalog data for one or more course codes. "
        "Unknown codes are silently omitted. "
        "Requires between 1 and 20 `codes` query parameters (uppercase, no spaces)."
    ),
    responses={
        200: {
            "description": "List of found courses matching requested codes.",
            "content": {
                "application/json": {
                    "example": EXAMPLE_CATALOG_RESPONSE,
                }
            },
        },
        422: {
            "description": "Validation error (invalid code count or invalid format).",
        },
        503: {
            "description": "Database unavailable.",
        },
    },
)
def get_courses(
    codes: List[str] = Query(
        default=[],
        description="Course codes to look up (repeatable, max 20). Example: `codes=CS3358&codes=CS1428`",
        openapi_examples={
            "single": {
                "summary": "Single course lookup",
                "value": ["CS3358"],
            },
            "multiple": {
                "summary": "Multiple courses lookup",
                "value": ["CS1428", "CS2318", "CS3358"],
            },
        },
    ),
) -> List[CatalogResponse]:
    # ── Validate ──────────────────────────────────────────────────────────────
    if len(codes) == 0:
        raise HTTPException(
            status_code=422,
            detail="At least one course code must be provided.",
        )
    if len(codes) > _MAX_CODES:
        raise HTTPException(
            status_code=422,
            detail=f"Too many codes: {len(codes)} provided, maximum is {_MAX_CODES}.",
        )
    for code in codes:
        if code != code.upper() or " " in code:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid course code '{code}': must be uppercase with no spaces.",
            )

    # ── Query DB ──────────────────────────────────────────────────────────────
    try:
        with database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_QUERY, (codes,))
                rows = cur.fetchall()
    except Exception as exc:
        logger.error("Database error while fetching courses: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable.") from exc

    # ── Map rows to response objects ──────────────────────────────────────────
    results: List[CatalogResponse] = []
    for row in rows:
        course_code, course_name, prereq_tree, coreq_tree, requirements_parsed = row
        db_row = CourseRow(
            course_code=course_code,
            course_name=course_name,
            prereq_tree=prereq_tree,   # psycopg2 returns JSONB as a dict already
            coreq_tree=coreq_tree,
            requirements_parsed=requirements_parsed if requirements_parsed is not None else False,
        )
        results.append(db_row.to_catalog_response())

    return results
