"""Offline tests for the syllabus ingest pipeline.

These tests use saved fixture files modeled after real API responses.
No network access or database is required.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from ingest.syllabus.fetcher import semester_to_label
from ingest.syllabus.models import SyllabusRecord, ValidationResult
from ingest.syllabus.parser import parse_classes_into_records
from ingest.syllabus.validator import validate_batch

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# ── Fixtures (loaded once) ─────────────────────────────────────────────

@pytest.fixture()
def cs_courses():
    return _load("cs_courses.json")


@pytest.fixture()
def course_details():
    return _load("course_details_CS1428.json")


@pytest.fixture()
def classes_data():
    return _load("classes_CS1428_202510.json")


@pytest.fixture()
def instructor_cache():
    """Pre-populated instructor cache from fixture files."""
    cache = {}
    for p in FIXTURES.glob("instructor_*.json"):
        data = json.loads(p.read_text())
        # Extract plid from filename: instructor_x9028bf7ba7de.json → x9028bf7ba7de
        plid = p.stem.replace("instructor_", "")
        cache[plid] = data.get("displayname", "")
    return cache


# ── semester_to_label ──────────────────────────────────────────────────

class TestSemesterToLabel:
    def test_fall_2024(self):
        # 202510 → Fall, year decremented → Fall 2024
        assert semester_to_label("202510") == "Fall 2024"

    def test_spring_2025(self):
        assert semester_to_label("202530") == "Spring 2025"

    def test_summer_2025(self):
        assert semester_to_label("202550") == "Summer 2025"

    def test_fall_2026(self):
        assert semester_to_label("202710") == "Fall 2026"

    def test_spring_2026(self):
        assert semester_to_label("202630") == "Spring 2026"

    def test_summer_code_06(self):
        assert semester_to_label("202506") == "Summer 2025"

    def test_summer_code_07_post_2011(self):
        # After 2011, month 07 → treated as 06 (Summer)
        assert semester_to_label("202507") == "Summer 2025"

    def test_summer_code_07_pre_2012(self):
        # At or before 2011, month 07 stays as Summer I
        assert semester_to_label("201107") == "Summer I 2011"

    def test_unknown_month(self):
        assert semester_to_label("202599") == "Unknown(99) 2025"


# ── Parser ─────────────────────────────────────────────────────────────

class TestParser:
    def test_basic_parsing(self, classes_data, instructor_cache):
        records = parse_classes_into_records(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            credit_hours=4,
            semester_code="202510",
            classes=classes_data["classes"],
            instructor_cache=instructor_cache,
        )
        assert len(records) == 3  # three class sections in fixture

    def test_fields_populated(self, classes_data, instructor_cache):
        records = parse_classes_into_records(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            credit_hours=4,
            semester_code="202510",
            classes=classes_data["classes"],
            instructor_cache=instructor_cache,
        )
        # Check the first record (section 005, instructor Cam Bradley)
        rec = [r for r in records if r.section == "005"][0]
        assert rec.course_code == "CS1428"
        assert rec.course_name == "FOUNDATIONS OF COMPUTER SCI I"
        assert rec.semester == "Fall 2024"
        assert rec.semester_code == "202510"
        assert rec.instructor_name == "Cam Bradley"
        assert rec.instructor_plid == "x9028bf7ba7de"
        assert rec.has_syllabus is True
        assert rec.credit_hours == 4
        assert rec.index_num == 251018765
        assert "getsyllabus.py?class=251018765" in rec.source_url

    def test_syllabus_false_preserved(self, classes_data, instructor_cache):
        records = parse_classes_into_records(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            credit_hours=4,
            semester_code="202510",
            classes=classes_data["classes"],
            instructor_cache=instructor_cache,
        )
        rec = [r for r in records if r.section == "099"][0]
        assert rec.has_syllabus is False

    def test_unknown_instructor(self, classes_data):
        # Empty cache → instructor_name should be None
        records = parse_classes_into_records(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            credit_hours=4,
            semester_code="202510",
            classes=classes_data["classes"],
            instructor_cache={},
        )
        for rec in records:
            assert rec.instructor_name is None

    def test_source_url_unique_per_section(self, classes_data, instructor_cache):
        records = parse_classes_into_records(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            credit_hours=4,
            semester_code="202510",
            classes=classes_data["classes"],
            instructor_cache=instructor_cache,
        )
        urls = [r.source_url for r in records]
        assert len(urls) == len(set(urls)), "source_url must be unique per section"

    def test_missing_indexnum_skipped(self, instructor_cache):
        """A class entry without indexnum should be skipped, not crash."""
        classes = [{"syllabus": True, "section": "001", "instructors": []}]
        records = parse_classes_into_records(
            course_code="CS9999",
            course_name="TEST",
            credit_hours=3,
            semester_code="202510",
            classes=classes,
            instructor_cache=instructor_cache,
        )
        assert len(records) == 0

    def test_credit_hours_none(self, classes_data, instructor_cache):
        """credit_hours can be None without breaking anything."""
        records = parse_classes_into_records(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            credit_hours=None,
            semester_code="202510",
            classes=classes_data["classes"],
            instructor_cache=instructor_cache,
        )
        assert all(r.credit_hours is None for r in records)

    def test_optional_fields_are_none_not_fabricated(self, classes_data):
        """original_format and syllabus_filename start as None."""
        records = parse_classes_into_records(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            credit_hours=4,
            semester_code="202510",
            classes=classes_data["classes"],
            instructor_cache={},
        )
        for rec in records:
            assert rec.original_format is None
            assert rec.syllabus_filename is None


# ── Validator ──────────────────────────────────────────────────────────

def _make_record(**overrides) -> SyllabusRecord:
    defaults = dict(
        course_code="CS1428",
        course_name="FOUNDATIONS OF COMPUTER SCI I",
        section="005",
        semester="Fall 2024",
        semester_code="202510",
        instructor_name="Test Person",
        instructor_plid="xtest",
        source_url="https://api.hb2504.txst.edu/py/getsyllabus.py?class=999",
        has_syllabus=True,
        original_format=None,
        syllabus_filename=None,
        credit_hours=4,
        index_num=999,
    )
    defaults.update(overrides)
    return SyllabusRecord(**defaults)


class TestValidator:
    def test_valid_record(self):
        result = validate_batch([_make_record()])
        assert result.ok
        assert len(result.valid) == 1

    def test_missing_course_code(self):
        result = validate_batch([_make_record(course_code="")])
        assert not result.ok
        assert len(result.errors) == 1
        assert "course_code" in result.errors[0][1]

    def test_missing_course_name(self):
        result = validate_batch([_make_record(course_name="")])
        assert not result.ok
        assert "course_name" in result.errors[0][1]

    def test_missing_section(self):
        result = validate_batch([_make_record(section="")])
        assert not result.ok
        assert "section" in result.errors[0][1]

    def test_missing_source_url(self):
        result = validate_batch([_make_record(source_url="")])
        assert not result.ok
        assert "source_url" in result.errors[0][1]

    def test_duplicate_source_url(self):
        rec = _make_record()
        result = validate_batch([rec, rec])
        # First passes, second is duplicate
        assert len(result.valid) == 1
        assert len(result.errors) == 1
        assert "duplicate" in result.errors[0][1]

    def test_optional_fields_can_be_none(self):
        rec = _make_record(
            instructor_name=None,
            instructor_plid=None,
            original_format=None,
            syllabus_filename=None,
            credit_hours=None,
        )
        result = validate_batch([rec])
        assert result.ok

    def test_multiple_valid_records(self):
        records = [
            _make_record(source_url=f"https://example.com/s?class={i}", index_num=i)
            for i in range(5)
        ]
        result = validate_batch(records)
        assert result.ok
        assert len(result.valid) == 5

    def test_mixed_valid_and_invalid(self):
        records = [
            _make_record(source_url="https://example.com/s?class=1", index_num=1),
            _make_record(source_url="", index_num=2),  # invalid
            _make_record(source_url="https://example.com/s?class=3", index_num=3),
        ]
        result = validate_batch(records)
        assert len(result.valid) == 2
        assert len(result.errors) == 1

    def test_summary_format(self):
        rec = _make_record(course_code="")
        result = validate_batch([rec])
        s = result.summary()
        assert "0 records" in s or "Validated" in s
        assert "ERROR" in s


# ── CS-section selection test ──────────────────────────────────────────

class TestCSCourseSelection:
    """Verify that the fixture courses list contains only CS courses."""

    def test_all_courses_are_cs(self, cs_courses):
        for course in cs_courses["courses"]:
            assert course["number"].startswith("CS"), (
                f"Expected CS prefix, got {course['number']}"
            )

    def test_course_has_number_and_title(self, cs_courses):
        for course in cs_courses["courses"]:
            assert "number" in course
            assert "title" in course
            assert len(course["number"]) > 0
            assert len(course["title"]) > 0


# ── Integration-style test (still offline) ─────────────────────────────

class TestEndToEnd:
    """Parse fixture data through the full parser→validator chain."""

    def test_full_pipeline_offline(self, classes_data, instructor_cache):
        records = parse_classes_into_records(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            credit_hours=4,
            semester_code="202510",
            classes=classes_data["classes"],
            instructor_cache=instructor_cache,
        )
        result = validate_batch(records)
        assert result.ok
        assert len(result.valid) == 3

        # Verify source URLs are all distinct
        urls = {r.source_url for r in result.valid}
        assert len(urls) == 3

        # Verify semester labels
        assert all(r.semester == "Fall 2024" for r in result.valid)

    def test_empty_classes_list(self, instructor_cache):
        records = parse_classes_into_records(
            course_code="CS9999",
            course_name="EMPTY COURSE",
            credit_hours=3,
            semester_code="202510",
            classes=[],
            instructor_cache=instructor_cache,
        )
        result = validate_batch(records)
        assert result.ok
        assert len(result.valid) == 0
