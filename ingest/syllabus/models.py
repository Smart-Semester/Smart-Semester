"""Data models for syllabus ingest records."""
from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Optional


@dataclasses.dataclass(frozen=True)
class SyllabusRecord:
    """One syllabus entry discovered from the HB 2504 site.

    Each record represents a single class section's syllabus for a specific
    course, semester, and section.  The source_url is the canonical download
    URL and serves as the uniqueness key for upserts.

    Traceability fields
    -------------------
    fetched_at   : UTC timestamp of the upstream API call that produced this
                   record.  Distinct from the DB row's created_at/updated_at,
                   which track row lifecycle rather than data freshness.
    catalog_year : Academic year the data belongs to, e.g. ``'2024-2025'``.
                   None when the pipeline has not been told the catalog year.
    source_host  : Hostname of the upstream API, e.g.
                   ``'api.hb2504.txst.edu'``.  Used to distinguish data
                   origins when multiple sources are ingested.
    """

    course_code: str  # e.g. "CS1428"
    course_name: str  # e.g. "FOUNDATIONS OF COMPUTER SCI I"
    section: str  # e.g. "005"
    semester: str  # human-readable, e.g. "Fall 2024"
    semester_code: str  # raw API code, e.g. "202510"
    instructor_name: Optional[str]  # may be None if lookup fails
    instructor_plid: Optional[str]  # hashed PL-ID from the API
    source_url: str  # syllabus download URL (uniqueness key)
    has_syllabus: bool  # whether the API says a syllabus exists
    original_format: Optional[str]  # e.g. "application/pdf"
    syllabus_filename: Optional[str]  # from Content-Disposition header
    credit_hours: Optional[int]  # from course details
    index_num: int  # class index number from the API
    # ── traceability ──────────────────────────────────────────────────
    fetched_at: datetime  # UTC time this record was fetched from the API
    catalog_year: Optional[str]  # e.g. "2024-2025"; None if not provided
    source_host: str  # e.g. "api.hb2504.txst.edu"


@dataclasses.dataclass
class ValidationResult:
    """Result of validating a batch of syllabus records."""

    valid: list[SyllabusRecord] = dataclasses.field(default_factory=list)
    errors: list[tuple[dict, str]] = dataclasses.field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        lines = [
            f"Validated {len(self.valid)} records, {len(self.errors)} errors.",
        ]
        for raw, msg in self.errors:
            lines.append(f"  ERROR: {msg}  (raw={raw!r})")
        return "\n".join(lines)
