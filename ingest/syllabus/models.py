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


class DownloadStatus:
    """Status of attempting to download a syllabus PDF."""

    PENDING = "PENDING"
    DOWNLOADED = "DOWNLOADED"
    MISSING = "MISSING"
    EXCEEDS_SIZE_LIMIT = "EXCEEDS_SIZE_LIMIT"
    UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"


class ExtractionStatus:
    """Status of extracting text from a downloaded syllabus document."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    SCANNED_NEEDS_OCR = "SCANNED_NEEDS_OCR"
    MALFORMED_PDF = "MALFORMED_PDF"
    PASSWORD_PROTECTED = "PASSWORD_PROTECTED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclasses.dataclass(frozen=True)
class SyllabusDocumentRecord:
    """A downloaded syllabus document and its extracted text.

    Stored in catalog.syllabus_documents. Retains document metadata,
    integrity checks, content hash, extracted raw text, and manual review flags.
    """

    syllabus_id: str  # logical / FK reference to catalog.syllabi.syllabus_id
    source_url: str
    file_path: Optional[str] = None
    content_type: Optional[str] = None
    original_filename: Optional[str] = None
    content_hash: Optional[str] = None  # SHA-256 hex digest
    file_size: Optional[int] = None  # in bytes
    download_status: str = DownloadStatus.PENDING
    extraction_status: str = ExtractionStatus.PENDING
    extracted_text: Optional[str] = None
    page_count: Optional[int] = None
    character_count: Optional[int] = None
    error_message: Optional[str] = None
    manual_review_required: bool = False
    manual_review_reason: Optional[str] = None
    manual_review_notes: Optional[str] = None
    downloaded_at: Optional[datetime] = None
    extracted_at: Optional[datetime] = None
    document_id: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class ObservationRecord:
    """A structured observation extracted from a syllabus document.

    Stored in catalog.syllabus_observations separately from canonical
    catalog.courses fields. Preserves source-document provenance (snippets,
    content hash, document ID, URL) so future LLM or rule-based course
    summaries can audit and trace claims back to specific syllabus excerpts.
    """

    syllabus_id: str
    course_code: str
    semester_code: str
    category: str  # e.g. "grading_breakdown", "textbook", "topics", "workload"
    observation_key: str  # e.g. "Exams", "Homework", "Required Book"
    observation_value: str  # e.g. "40%", "Starting Out with C++"
    context_snippet: Optional[str] = None  # verbatim text excerpt from syllabus
    confidence: float = 1.0  # confidence score (0.0 - 1.0)
    provenance: Optional[dict] = None  # e.g. {"source_url": ..., "content_hash": ...}
    document_id: Optional[str] = None
    observation_id: Optional[str] = None
    created_at: Optional[datetime] = None

