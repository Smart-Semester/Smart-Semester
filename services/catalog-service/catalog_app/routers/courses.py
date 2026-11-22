"""
courses.py — GET /courses router.

Spec (from docs/Catalog-API-Contract.md):
  GET /courses?codes=CS3358&codes=CS1428
  - `codes` is repeatable; 1–20 codes required; 422 if 0 or >20.
  - Codes must be uppercase with no spaces.
  - Unknown codes are silently omitted.
  - Returns a JSON array of CatalogResponse objects.

Each CatalogResponse now includes a `syllabus_documents` list.  The join
strategy is:

  1. Left-join catalog.courses → catalog.syllabi → catalog.syllabus_documents
     so courses with canonical data but no documents get syllabus_documents=[].

  2. Union with a query over catalog.syllabi (LEFT JOIN syllabus_documents) for
     course codes found *only* in syllabi (not in catalog.courses).  For those
     rows: title comes from syllabi.course_name, prereqs/coreqs are null, and
     requirements_parsed is false.

  file_path is never selected — it must not appear in the API response.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from catalog_app import database
from catalog_app.schemas import CatalogResponse, CourseRow, SyllabusDocument

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_CODES = 20

# ─────────────────────────────────────────────────────────────────────────────
# SQL
# ─────────────────────────────────────────────────────────────────────────────
#
# Single query using a CTE so we hit the DB once.
#
# Part A — canonical courses (LEFT JOINed to syllabi + documents):
#   • Returns one row per (course_code, document_id).
#   • A course with no matching syllabi/documents produces a single row with
#     NULLs for all syllabus/document columns.
#
# Part B — syllabus-only courses (codes in syllabi but NOT in catalog.courses):
#   • Uses catalog.syllabi.course_name as the title.
#   • prereq_tree / coreq_tree / requirements_parsed are NULL / FALSE.
#
# ORDER BY ensures deterministic ordering within each course for multi-document
# cases.
# ─────────────────────────────────────────────────────────────────────────────

_QUERY = """
WITH requested AS (
    SELECT unnest(%s::text[]) AS course_code
),
canonical AS (
    SELECT
        c.course_code,
        c.course_name,
        c.prereq_tree,
        c.coreq_tree,
        COALESCE(c.requirements_parsed, FALSE) AS requirements_parsed,
        TRUE  AS from_catalog,

        -- syllabus_documents columns (NULL when no document exists)
        sd.document_id::text,
        sd.source_url     AS doc_source_url,
        sd.content_type,
        sd.original_filename,
        sd.content_hash,
        sd.file_size,
        sd.download_status,
        sd.extraction_status,
        sd.extracted_text,
        sd.page_count,
        sd.character_count,
        sd.manual_review_required,
        sd.manual_review_reason,
        sd.manual_review_notes,
        sd.downloaded_at,
        sd.extracted_at,

        -- denormalised from catalog.syllabi
        sy.semester,
        sy.semester_code,
        sy.section,
        sy.instructor_name,
        sy.has_syllabus

    FROM requested r
    JOIN catalog.courses c ON c.course_code = r.course_code
    LEFT JOIN catalog.syllabi sy ON sy.course_code = c.course_code
    LEFT JOIN catalog.syllabus_documents sd ON sd.syllabus_id = sy.syllabus_id
),
syllabus_only AS (
    SELECT
        sy.course_code,
        sy.course_name,
        NULL::jsonb  AS prereq_tree,
        NULL::jsonb  AS coreq_tree,
        FALSE        AS requirements_parsed,
        FALSE        AS from_catalog,

        sd.document_id::text,
        sd.source_url     AS doc_source_url,
        sd.content_type,
        sd.original_filename,
        sd.content_hash,
        sd.file_size,
        sd.download_status,
        sd.extraction_status,
        sd.extracted_text,
        sd.page_count,
        sd.character_count,
        sd.manual_review_required,
        sd.manual_review_reason,
        sd.manual_review_notes,
        sd.downloaded_at,
        sd.extracted_at,

        sy.semester,
        sy.semester_code,
        sy.section,
        sy.instructor_name,
        sy.has_syllabus

    FROM requested r
    JOIN catalog.syllabi sy ON sy.course_code = r.course_code
    LEFT JOIN catalog.syllabus_documents sd ON sd.syllabus_id = sy.syllabus_id
    WHERE NOT EXISTS (
        SELECT 1 FROM catalog.courses c WHERE c.course_code = r.course_code
    )
)
SELECT *
FROM   canonical
UNION ALL
SELECT *
FROM   syllabus_only
ORDER BY course_code, document_id NULLS FIRST
"""

# Column index constants (must match SELECT order above)
_COL_COURSE_CODE           = 0
_COL_COURSE_NAME           = 1
_COL_PREREQ_TREE           = 2
_COL_COREQ_TREE            = 3
_COL_REQUIREMENTS_PARSED   = 4
_COL_FROM_CATALOG          = 5   # internal — not exposed
_COL_DOCUMENT_ID           = 6
_COL_DOC_SOURCE_URL        = 7
_COL_CONTENT_TYPE          = 8
_COL_ORIGINAL_FILENAME     = 9
_COL_CONTENT_HASH          = 10
_COL_FILE_SIZE             = 11
_COL_DOWNLOAD_STATUS       = 12
_COL_EXTRACTION_STATUS     = 13
_COL_EXTRACTED_TEXT        = 14
_COL_PAGE_COUNT            = 15
_COL_CHARACTER_COUNT       = 16
_COL_MANUAL_REVIEW_REQUIRED = 17
_COL_MANUAL_REVIEW_REASON  = 18
_COL_MANUAL_REVIEW_NOTES   = 19
_COL_DOWNLOADED_AT         = 20
_COL_EXTRACTED_AT          = 21
_COL_SEMESTER              = 22
_COL_SEMESTER_CODE         = 23
_COL_SECTION               = 24
_COL_INSTRUCTOR_NAME       = 25
_COL_HAS_SYLLABUS          = 26


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
        "syllabus_documents": [],
    }
]


@router.get(
    "/courses",
    response_model=List[CatalogResponse],
    summary="Fetch course catalog entries",
    description=(
        "Return catalog data for one or more course codes. "
        "Unknown codes are silently omitted. "
        "Requires between 1 and 20 `codes` query parameters (uppercase, no spaces). "
        "Each result includes a `syllabus_documents` list with all associated "
        "syllabus documents (empty list when none exist). "
        "The server-local `file_path` column is never exposed."
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

    # ── Aggregate rows into per-course buckets ────────────────────────────────
    # Each DB row represents one (course, document) pair.  We group by
    # course_code, keeping track of catalog metadata from the first row and
    # accumulating SyllabusDocument objects.

    # Preserve insertion order so callers get a stable ordering.
    course_meta: Dict[str, Dict[str, Any]] = {}
    course_docs: Dict[str, List[SyllabusDocument]] = defaultdict(list)
    # Track which document_ids we've already appended (dedup safety).
    seen_doc_ids: Dict[str, set] = defaultdict(set)

    for row in rows:
        code = row[_COL_COURSE_CODE]

        if code not in course_meta:
            course_meta[code] = {
                "course_name":          row[_COL_COURSE_NAME],
                "prereq_tree":          row[_COL_PREREQ_TREE],
                "coreq_tree":           row[_COL_COREQ_TREE],
                "requirements_parsed":  row[_COL_REQUIREMENTS_PARSED],
            }

        document_id: Optional[str] = row[_COL_DOCUMENT_ID]
        if document_id is None:
            # This course has no matching syllabus_documents row — skip doc append.
            continue

        if document_id in seen_doc_ids[code]:
            continue
        seen_doc_ids[code].add(document_id)

        course_docs[code].append(
            SyllabusDocument(
                document_id=document_id,
                source_url=row[_COL_DOC_SOURCE_URL],
                content_type=row[_COL_CONTENT_TYPE],
                original_filename=row[_COL_ORIGINAL_FILENAME],
                content_hash=row[_COL_CONTENT_HASH],
                file_size=row[_COL_FILE_SIZE],
                download_status=row[_COL_DOWNLOAD_STATUS],
                extraction_status=row[_COL_EXTRACTION_STATUS],
                extracted_text=row[_COL_EXTRACTED_TEXT],
                page_count=row[_COL_PAGE_COUNT],
                character_count=row[_COL_CHARACTER_COUNT],
                manual_review_required=row[_COL_MANUAL_REVIEW_REQUIRED],
                manual_review_reason=row[_COL_MANUAL_REVIEW_REASON],
                manual_review_notes=row[_COL_MANUAL_REVIEW_NOTES],
                downloaded_at=row[_COL_DOWNLOADED_AT],
                extracted_at=row[_COL_EXTRACTED_AT],
                semester=row[_COL_SEMESTER],
                semester_code=row[_COL_SEMESTER_CODE],
                section=row[_COL_SECTION],
                instructor_name=row[_COL_INSTRUCTOR_NAME],
                has_syllabus=row[_COL_HAS_SYLLABUS],
            )
        )

    # ── Build response list ───────────────────────────────────────────────────
    results: List[CatalogResponse] = []
    for code, meta in course_meta.items():
        db_row = CourseRow(
            course_code=code,
            course_name=meta["course_name"],
            prereq_tree=meta["prereq_tree"],
            coreq_tree=meta["coreq_tree"],
            requirements_parsed=meta["requirements_parsed"] if meta["requirements_parsed"] is not None else False,
        )
        response = db_row.to_catalog_response()
        response.syllabus_documents = course_docs.get(code, [])
        results.append(response)

    return results
