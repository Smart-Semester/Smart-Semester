"""Tests for ObservationExtractor: structured observations and provenance preservation."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingest.syllabus.extractor import PDFTextExtractor
from ingest.syllabus.models import (
    DownloadStatus,
    ExtractionStatus,
    SyllabusDocumentRecord,
    SyllabusRecord,
)
from ingest.syllabus.observations import ObservationExtractor

FIXTURES = Path(__file__).parent / "fixtures"


def _make_syllabus_record() -> SyllabusRecord:
    return SyllabusRecord(
        course_code="CS1428",
        course_name="FOUNDATIONS OF COMPUTER SCI I",
        section="001",
        semester="Fall 2024",
        semester_code="202510",
        instructor_name="Dr. Jane Doe",
        instructor_plid="plid123",
        source_url="https://hb2504.txst.edu/syllabi/CS1428_001.pdf",
        has_syllabus=True,
        original_format="application/pdf",
        syllabus_filename="CS1428.pdf",
        credit_hours=4,
        index_num=101,
        fetched_at=datetime.now(timezone.utc),
        catalog_year="2024-2025",
        source_host="api.hb2504.txst.edu",
    )


@pytest.fixture()
def valid_doc_record() -> SyllabusDocumentRecord:
    pdf_path = FIXTURES / "valid_syllabus.pdf"
    doc = SyllabusDocumentRecord(
        syllabus_id="00000000-0000-0000-0000-000000000001",
        source_url="https://hb2504.txst.edu/syllabi/CS1428_001.pdf",
        file_path=str(pdf_path),
        content_type="application/pdf",
        content_hash="hash987654321",
        original_filename="CS1428.pdf",
        download_status=DownloadStatus.DOWNLOADED,
    )
    extractor = PDFTextExtractor()
    return extractor.extract_text(doc, pdf_path)


class TestObservationExtractor:
    def test_extract_all_observations_from_valid_syllabus(self, valid_doc_record):
        syllabus = _make_syllabus_record()
        obs_extractor = ObservationExtractor()

        observations = obs_extractor.extract_observations(valid_doc_record, syllabus)

        assert len(observations) > 0

        # Check grading breakdown
        grading_obs = [o for o in observations if o.category == "grading_breakdown"]
        assert len(grading_obs) == 4
        keys = {o.observation_key: o.observation_value for o in grading_obs}
        assert keys["Programming Assignments"] == "30%"
        assert keys["Midterm Exams"] == "40%"
        assert keys["Final Exam"] == "20%"
        assert keys["Quizzes"] == "10%"

        # Check textbook
        textbook_obs = [o for o in observations if o.category == "textbook"]
        assert len(textbook_obs) == 1
        assert "Tony Gaddis" in textbook_obs[0].observation_value
        assert "Required Textbook:" in textbook_obs[0].context_snippet

        # Check topics
        topics_obs = [o for o in observations if o.category == "topics"]
        assert len(topics_obs) == 1
        assert "Variables" in topics_obs[0].observation_value
        assert "Pointers" in topics_obs[0].observation_value

        # Check workload
        workload_obs = [o for o in observations if o.category == "workload"]
        assert len(workload_obs) >= 2
        workload_vals = [o.observation_value.lower() for o in workload_obs]
        assert any("5 programming assignments" in v for v in workload_vals)
        assert any("2 midterm exams" in v for v in workload_vals)

        # Check office hours
        office_obs = [o for o in observations if o.category == "office_hours"]
        assert len(office_obs) == 1
        assert "Monday and Wednesday" in office_obs[0].observation_value

        # Check policies
        policy_obs = [o for o in observations if o.category == "course_policy"]
        assert len(policy_obs) >= 1
        policy_keys = [o.observation_key.lower() for o in policy_obs]
        assert any("late" in k for k in policy_keys)

    def test_provenance_preserved_on_all_observations(self, valid_doc_record):
        syllabus = _make_syllabus_record()
        obs_extractor = ObservationExtractor()

        observations = obs_extractor.extract_observations(valid_doc_record, syllabus)

        for obs in observations:
            assert obs.syllabus_id == "00000000-0000-0000-0000-000000000001"
            assert obs.course_code == "CS1428"
            assert obs.semester_code == "202510"
            assert obs.context_snippet is not None and len(obs.context_snippet) > 0
            assert obs.provenance is not None
            assert obs.provenance["source_url"] == syllabus.source_url
            assert obs.provenance["content_hash"] == valid_doc_record.content_hash
            assert obs.confidence > 0.0

    def test_no_observations_for_scanned_or_failed_doc(self):
        syllabus = _make_syllabus_record()
        scanned_doc = SyllabusDocumentRecord(
            syllabus_id="00000000-0000-0000-0000-000000000002",
            source_url=syllabus.source_url,
            extraction_status=ExtractionStatus.SCANNED_NEEDS_OCR,
            extracted_text=None,
            manual_review_required=True,
        )
        obs_extractor = ObservationExtractor()

        observations = obs_extractor.extract_observations(scanned_doc, syllabus)
        assert observations == []

    def test_no_observations_for_empty_text(self):
        syllabus = _make_syllabus_record()
        empty_doc = SyllabusDocumentRecord(
            syllabus_id="00000000-0000-0000-0000-000000000003",
            source_url=syllabus.source_url,
            extraction_status=ExtractionStatus.SUCCESS,
            extracted_text="",
        )
        obs_extractor = ObservationExtractor()

        observations = obs_extractor.extract_observations(empty_doc, syllabus)
        assert observations == []
