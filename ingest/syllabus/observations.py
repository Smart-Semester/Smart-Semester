"""Structured syllabus observation extraction with source provenance tracking.

Extracts structured observations (grading breakdown, textbooks, topics, workload,
office hours, policies) from raw syllabus text while preserving source-document
provenance.

These observations are stored in `catalog.syllabus_observations` and are kept
strictly separate from canonical catalog courses in `catalog.courses`.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from .models import (
    ExtractionStatus,
    ObservationRecord,
    SyllabusDocumentRecord,
    SyllabusRecord,
)

logger = logging.getLogger(__name__)

# ── Regex patterns for syllabus structures ────────────────────────────────────

# Grading component lines e.g. "Programming Assignments: 30%", "Exams - 40%"
GRADING_LINE_RE = re.compile(
    r"(?i)^[ \t]*(?:[-*•]?[ \t]*)?"
    r"((?:Programming\s+Assignments?|Assignments?|Homework|Midterm\s+Exams?|Final\s+Exam|Exams?|Quizzes?|Labs?|Projects?|Participation|Attendance))"
    r"[ \t]*[:=-][ \t]*(\d{1,2}(?:\.\d+)?\s*%)",
    re.MULTILINE,
)

# Textbook patterns e.g. "Required Textbook: Starting Out with C++..."
TEXTBOOK_RE = re.compile(
    r"(?i)(?:Required\s+Text(?:book)?|Textbooks?|Course\s+Materials?)\s*[:=-]\s*([^\n\r]+)"
)

# Topics section header and lines
TOPICS_HEADER_RE = re.compile(
    r"(?i)(?:Course\s+Topics?|Schedule\s+of\s+Topics?|Topics?\s+Covered|Course\s+Outline)\s*[:=-]\s*([^\n\r]+)"
)

# Workload metrics e.g. "5 programming assignments", "2 midterm exams"
WORKLOAD_RE = re.compile(
    r"(?i)\b(\d+)\s+((?:programming\s+assignments?|homework\s+assignments?|midterm\s+exams?|final\s+exams?|projects?|quizzes))\b"
)

# Office hours patterns
OFFICE_HOURS_RE = re.compile(
    r"(?i)(?:Office\s+Hours?)\s*[:=-]\s*([^\n\r]+)"
)

# Policies: late work, attendance, integrity
POLICIES_RE = re.compile(
    r"(?i)(Late\s+Policy|Attendance\s+Policy|Academic\s+Integrity)\s*[:=-]\s*([^\n\r]+)"
)


class ObservationExtractor:
    """Extracts structured observations from syllabus text with source provenance."""

    def extract_observations(
        self,
        doc_record: SyllabusDocumentRecord,
        syllabus: SyllabusRecord,
    ) -> list[ObservationRecord]:
        """Extract structured observations from a document record.

        Returns a list of ObservationRecords with source provenance.
        Returns an empty list if document has no extracted text or extraction failed.
        """
        if (
            doc_record.extraction_status != ExtractionStatus.SUCCESS
            or not doc_record.extracted_text
        ):
            return []

        text = doc_record.extracted_text
        observations: list[ObservationRecord] = []
        syllabus_id = getattr(syllabus, "syllabus_id", "") or str(doc_record.syllabus_id)
        base_provenance = {
            "source_url": syllabus.source_url,
            "content_hash": doc_record.content_hash,
            "original_filename": doc_record.original_filename,
        }

        # ── 1. Grading Breakdown ──────────────────────────────────────────────
        for match in GRADING_LINE_RE.finditer(text):
            component = match.group(1).strip()
            weight = match.group(2).strip()
            snippet = match.group(0).strip()

            observations.append(
                ObservationRecord(
                    syllabus_id=syllabus_id,
                    course_code=syllabus.course_code,
                    semester_code=syllabus.semester_code,
                    category="grading_breakdown",
                    observation_key=component,
                    observation_value=weight,
                    context_snippet=snippet,
                    confidence=0.95,
                    provenance={**base_provenance, "pattern": "grading_percentage"},
                    document_id=doc_record.document_id,
                )
            )

        # ── 2. Textbook / Materials ───────────────────────────────────────────
        for match in TEXTBOOK_RE.finditer(text):
            book_info = match.group(1).strip()
            snippet = match.group(0).strip()
            if book_info:
                observations.append(
                    ObservationRecord(
                        syllabus_id=syllabus_id,
                        course_code=syllabus.course_code,
                        semester_code=syllabus.semester_code,
                        category="textbook",
                        observation_key="Required Textbook",
                        observation_value=book_info,
                        context_snippet=snippet,
                        confidence=0.90,
                        provenance={**base_provenance, "pattern": "textbook_match"},
                        document_id=doc_record.document_id,
                    )
                )

        # ── 3. Course Topics ──────────────────────────────────────────────────
        for match in TOPICS_HEADER_RE.finditer(text):
            topics_content = match.group(1).strip()
            snippet = match.group(0).strip()
            if topics_content:
                observations.append(
                    ObservationRecord(
                        syllabus_id=syllabus_id,
                        course_code=syllabus.course_code,
                        semester_code=syllabus.semester_code,
                        category="topics",
                        observation_key="Course Topics",
                        observation_value=topics_content,
                        context_snippet=snippet,
                        confidence=0.85,
                        provenance={**base_provenance, "pattern": "topics_header"},
                        document_id=doc_record.document_id,
                    )
                )

        # ── 4. Workload ───────────────────────────────────────────────────────
        for match in WORKLOAD_RE.finditer(text):
            count_str = match.group(1).strip()
            item_type = match.group(2).strip()
            snippet = match.group(0).strip()
            observations.append(
                ObservationRecord(
                    syllabus_id=syllabus_id,
                    course_code=syllabus.course_code,
                    semester_code=syllabus.semester_code,
                    category="workload",
                    observation_key=item_type.capitalize(),
                    observation_value=f"{count_str} {item_type}",
                    context_snippet=snippet,
                    confidence=0.90,
                    provenance={**base_provenance, "pattern": "workload_count"},
                    document_id=doc_record.document_id,
                )
            )

        # ── 5. Office Hours ───────────────────────────────────────────────────
        for match in OFFICE_HOURS_RE.finditer(text):
            hours_info = match.group(1).strip()
            snippet = match.group(0).strip()
            if hours_info:
                observations.append(
                    ObservationRecord(
                        syllabus_id=syllabus_id,
                        course_code=syllabus.course_code,
                        semester_code=syllabus.semester_code,
                        category="office_hours",
                        observation_key="Office Hours",
                        observation_value=hours_info,
                        context_snippet=snippet,
                        confidence=0.90,
                        provenance={**base_provenance, "pattern": "office_hours"},
                        document_id=doc_record.document_id,
                    )
                )

        # ── 6. Course Policies ────────────────────────────────────────────────
        for match in POLICIES_RE.finditer(text):
            policy_name = match.group(1).strip()
            policy_val = match.group(2).strip()
            snippet = match.group(0).strip()
            if policy_val:
                observations.append(
                    ObservationRecord(
                        syllabus_id=syllabus_id,
                        course_code=syllabus.course_code,
                        semester_code=syllabus.semester_code,
                        category="course_policy",
                        observation_key=policy_name,
                        observation_value=policy_val,
                        context_snippet=snippet,
                        confidence=0.85,
                        provenance={**base_provenance, "pattern": "course_policy"},
                        document_id=doc_record.document_id,
                    )
                )

        return observations
