"""Validator — checks a batch of SyllabusRecords for required fields."""
from __future__ import annotations

import dataclasses
from typing import Any

from .models import SyllabusRecord, ValidationResult

# Fields that must be non-empty for a record to be valid.
REQUIRED_FIELDS = ("course_code", "course_name", "section", "semester", "source_url")


def validate_batch(records: list[SyllabusRecord]) -> ValidationResult:
    """Validate a list of SyllabusRecords.

    Returns a ValidationResult containing valid records and errors.
    """
    result = ValidationResult()
    seen_urls: set[str] = set()

    for rec in records:
        raw = dataclasses.asdict(rec)
        errors: list[str] = []

        for field in REQUIRED_FIELDS:
            val = getattr(rec, field, None)
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(f"missing required field '{field}'")

        if rec.source_url in seen_urls:
            errors.append(f"duplicate source_url '{rec.source_url}'")

        if errors:
            result.errors.append((raw, "; ".join(errors)))
        else:
            seen_urls.add(rec.source_url)
            result.valid.append(rec)

    return result
