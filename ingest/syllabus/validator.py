"""Validator — checks a batch of SyllabusRecords for data quality.

Checks performed per record
---------------------------
- Required fields are non-empty.
- course_code matches the expected format (e.g. "CS1428", "MATH2471").
- semester_code matches the expected YYYYMM format.
- source_url is a non-empty string starting with "https://".
- source_url is not a duplicate within the batch.
- has_syllabus=False records are accepted and pass through (not filtered out).
  They represent sections the pipeline has seen but that have no syllabus yet;
  they are stored so the absence of a syllabus can be reported to users.
"""
from __future__ import annotations

import dataclasses
import re

from .models import SyllabusRecord, ValidationResult

# Fields that must be non-empty for a record to be valid.
REQUIRED_FIELDS = ("course_code", "course_name", "section", "semester", "source_url")

# e.g. CS1428, MATH2471, PHIL1305, ENG2254, COMM1315
_COURSE_CODE_RE = re.compile(r"^[A-Z]{2,6}\d{4}[A-Z]?$")

# YYYYMM where MM is a plausible month code used by the HB 2504 API.
_SEMESTER_CODE_RE = re.compile(r"^\d{4}(05|06|07|10|12|30|50)$")

# Syllabus source URLs must be absolute HTTPS URLs.
_URL_RE = re.compile(r"^https://")


def validate_batch(records: list[SyllabusRecord]) -> ValidationResult:
    """Validate a list of SyllabusRecords.

    Records with has_syllabus=False are valid and are included in the output —
    they represent sections confirmed to exist but without an available
    syllabus, and storing them lets downstream tools report this accurately.

    Returns a ValidationResult containing valid records and errors.
    """
    result = ValidationResult()
    seen_urls: set[str] = set()

    for rec in records:
        raw = dataclasses.asdict(rec)
        errors: list[str] = []

        # ── Required-field presence ───────────────────────────────────────
        for field in REQUIRED_FIELDS:
            val = getattr(rec, field, None)
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(f"missing required field '{field}'")

        # ── Format checks (only when the field is present) ────────────────
        if rec.course_code and not _COURSE_CODE_RE.match(rec.course_code):
            errors.append(
                f"course_code '{rec.course_code}' does not match expected format "
                "(2-6 uppercase letters followed by 4 digits, e.g. 'CS1428')"
            )

        if rec.semester_code and not _SEMESTER_CODE_RE.match(rec.semester_code):
            errors.append(
                f"semester_code '{rec.semester_code}' does not match expected "
                "YYYYMM format with a known month code (05/06/07/10/12/30/50)"
            )

        if rec.source_url and not _URL_RE.match(rec.source_url):
            errors.append(
                f"source_url '{rec.source_url}' must be an absolute HTTPS URL"
            )

        # ── Batch-level duplicate check ───────────────────────────────────
        if rec.source_url and rec.source_url in seen_urls:
            errors.append(f"duplicate source_url '{rec.source_url}'")

        if errors:
            result.errors.append((raw, "; ".join(errors)))
        else:
            seen_urls.add(rec.source_url)
            result.valid.append(rec)

    return result
