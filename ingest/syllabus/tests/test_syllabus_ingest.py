"""Offline tests for the syllabus ingest pipeline.

These tests use saved fixture files modeled after real API responses.
No network access or database is required.
"""
from __future__ import annotations

import json
import pathlib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.client import HTTPMessage
from unittest.mock import MagicMock, call, patch

import pytest

from ingest.syllabus.fetcher import HB2504Fetcher, semester_to_label
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
        fetched_at=datetime(2026, 11, 9, 5, 30, 0, tzinfo=timezone.utc),
        catalog_year="2024-2025",
        source_host="api.hb2504.txst.edu",
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


# ── HB2504Fetcher retry / backoff ─────────────────────────────────────

def _make_http_error(status: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    """Build a minimal HTTPError for testing."""
    headers = HTTPMessage()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        url="https://example.com",
        code=status,
        msg=f"HTTP {status}",
        hdrs=headers,
        fp=None,
    )


def _make_fetcher(**kwargs) -> HB2504Fetcher:
    """Return a fetcher with no inter-request delay (speeds up tests)."""
    kwargs.setdefault("delay", 0.0)
    kwargs.setdefault("backoff_base", 0.0)  # zero sleep in tests
    return HB2504Fetcher(**kwargs)


class TestFetcherRetry:
    """Verify retry / backoff / Retry-After behaviour in _get_json."""

    def _urlopen_responses(self, *responses):
        """
        Build a side_effect list for urllib.request.urlopen.

        Each item in *responses* is either:
        - an Exception subclass instance  → raised on that call
        - a dict                          → returned as parsed JSON via a mock context manager
        """
        side_effects = []
        for r in responses:
            if isinstance(r, BaseException):
                side_effects.append(r)
            else:
                body = json.dumps(r).encode()
                mock_resp = MagicMock()
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = MagicMock(return_value=False)
                mock_resp.read.return_value = body
                mock_resp.decode = body.decode
                side_effects.append(mock_resp)
        return side_effects

    @patch("ingest.syllabus.fetcher.urllib.request.urlopen")
    def test_success_on_first_attempt(self, mock_urlopen):
        """Happy-path: single successful request, no retries."""
        payload = {"courses": []}
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(payload).encode()
        mock_urlopen.return_value = mock_resp

        fetcher = _make_fetcher()
        result = fetcher._get_json("getcoursesfordepartment.py", {"department": "CS"})

        assert result == payload
        assert mock_urlopen.call_count == 1

    @patch("ingest.syllabus.fetcher.time.sleep")
    @patch("ingest.syllabus.fetcher.urllib.request.urlopen")
    def test_retries_on_503_then_succeeds(self, mock_urlopen, mock_sleep):
        """A 503 on the first attempt triggers a retry that succeeds."""
        payload = {"courses": []}
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(payload).encode()

        mock_urlopen.side_effect = [
            _make_http_error(503),
            mock_resp,
        ]

        fetcher = _make_fetcher()
        result = fetcher._get_json("getcoursesfordepartment.py")

        assert result == payload
        assert mock_urlopen.call_count == 2
        assert mock_sleep.call_count >= 1  # backoff sleep was called

    @patch("ingest.syllabus.fetcher.time.sleep")
    @patch("ingest.syllabus.fetcher.urllib.request.urlopen")
    def test_raises_after_max_retries(self, mock_urlopen, mock_sleep):
        """Persistent 503s exhaust all retries and re-raise the last error."""
        fetcher = _make_fetcher(max_retries=2)
        mock_urlopen.side_effect = _make_http_error(503)

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            fetcher._get_json("getcoursesfordepartment.py")

        assert exc_info.value.code == 503
        # First attempt + 2 retries = 3 total calls
        assert mock_urlopen.call_count == 3

    @patch("ingest.syllabus.fetcher.time.sleep")
    @patch("ingest.syllabus.fetcher.urllib.request.urlopen")
    def test_non_retryable_http_error_raises_immediately(self, mock_urlopen, mock_sleep):
        """A 404 is not retryable and must raise on the first attempt."""
        fetcher = _make_fetcher()
        mock_urlopen.side_effect = _make_http_error(404)

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            fetcher._get_json("getcoursesfordepartment.py")

        assert exc_info.value.code == 404
        assert mock_urlopen.call_count == 1
        mock_sleep.assert_not_called()

    @patch("ingest.syllabus.fetcher.time.sleep")
    @patch("ingest.syllabus.fetcher.urllib.request.urlopen")
    def test_429_uses_retry_after_header(self, mock_urlopen, mock_sleep):
        """A 429 with Retry-After header sleeps for the declared duration."""
        payload = {"courses": []}
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(payload).encode()

        mock_urlopen.side_effect = [
            _make_http_error(429, retry_after="5"),
            mock_resp,
        ]

        fetcher = _make_fetcher(backoff_base=99.0)  # backoff_base must NOT be used
        fetcher._get_json("getcoursesfordepartment.py")

        # The sleep called with Retry-After value (5 s), not the backoff formula
        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert 5.0 in sleep_calls

    @patch("ingest.syllabus.fetcher.time.sleep")
    @patch("ingest.syllabus.fetcher.urllib.request.urlopen")
    def test_network_error_retried(self, mock_urlopen, mock_sleep):
        """OSError (e.g. connection timeout) is retried."""
        payload = {"courses": []}
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(payload).encode()

        mock_urlopen.side_effect = [OSError("timed out"), mock_resp]

        fetcher = _make_fetcher()
        result = fetcher._get_json("getcoursesfordepartment.py")

        assert result == payload
        assert mock_urlopen.call_count == 2

    @patch("ingest.syllabus.fetcher.time.sleep")
    @patch("ingest.syllabus.fetcher.urllib.request.urlopen")
    def test_exponential_backoff_sequence(self, mock_urlopen, mock_sleep):
        """Backoff sleeps double on each retry attempt."""
        fetcher = _make_fetcher(max_retries=3, backoff_base=1.0, backoff_max=100.0)
        mock_urlopen.side_effect = _make_http_error(503)

        with pytest.raises(urllib.error.HTTPError):
            fetcher._get_json("getcoursesfordepartment.py")

        # Collect all sleep durations that look like backoff (> 0)
        sleep_durations = [c.args[0] for c in mock_sleep.call_args_list if c.args[0] > 0]
        # Should have 3 backoff sleeps: 1s, 2s, 4s
        assert sleep_durations == [1.0, 2.0, 4.0]

    def test_retry_after_helper_parses_numeric(self):
        """_retry_after returns float for a numeric Retry-After header."""
        fetcher = _make_fetcher()
        exc = _make_http_error(429, retry_after="12")
        assert fetcher._retry_after(exc) == 12.0

    def test_retry_after_helper_returns_none_on_missing(self):
        """_retry_after returns None when the header is absent."""
        fetcher = _make_fetcher()
        exc = _make_http_error(429, retry_after=None)
        assert fetcher._retry_after(exc) is None

    def test_retry_after_helper_returns_none_on_non_numeric(self):
        """_retry_after returns None for unparseable header values."""
        fetcher = _make_fetcher()
        exc = _make_http_error(429, retry_after="Wed, 09 Nov 2026 06:00:00 GMT")
        assert fetcher._retry_after(exc) is None


# ── Traceability fields ────────────────────────────────────────────────

class TestTraceabilityFields:
    """Verify fetched_at, catalog_year, and source_host propagate correctly."""

    def test_make_record_has_traceability_fields(self):
        rec = _make_record()
        assert rec.fetched_at == datetime(2026, 11, 9, 5, 30, 0, tzinfo=timezone.utc)
        assert rec.catalog_year == "2024-2025"
        assert rec.source_host == "api.hb2504.txst.edu"

    def test_parser_propagates_fetched_at(self, classes_data, instructor_cache):
        """fetched_at passed to parse_classes_into_records appears on each record."""
        ts = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        records = parse_classes_into_records(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            credit_hours=4,
            semester_code="202510",
            classes=classes_data["classes"],
            instructor_cache=instructor_cache,
            fetched_at=ts,
        )
        assert all(r.fetched_at == ts for r in records)

    def test_parser_propagates_catalog_year(self, classes_data, instructor_cache):
        records = parse_classes_into_records(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            credit_hours=4,
            semester_code="202510",
            classes=classes_data["classes"],
            instructor_cache=instructor_cache,
            catalog_year="2024-2025",
        )
        assert all(r.catalog_year == "2024-2025" for r in records)

    def test_parser_catalog_year_defaults_to_none(self, classes_data, instructor_cache):
        records = parse_classes_into_records(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            credit_hours=4,
            semester_code="202510",
            classes=classes_data["classes"],
            instructor_cache=instructor_cache,
        )
        assert all(r.catalog_year is None for r in records)

    def test_parser_propagates_source_host(self, classes_data, instructor_cache):
        records = parse_classes_into_records(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            credit_hours=4,
            semester_code="202510",
            classes=classes_data["classes"],
            instructor_cache=instructor_cache,
            source_host="catalog.txst.edu",
        )
        assert all(r.source_host == "catalog.txst.edu" for r in records)

    def test_parser_source_host_default(self, classes_data, instructor_cache):
        records = parse_classes_into_records(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            credit_hours=4,
            semester_code="202510",
            classes=classes_data["classes"],
            instructor_cache=instructor_cache,
        )
        assert all(r.source_host == "api.hb2504.txst.edu" for r in records)

    def test_parser_fetched_at_defaults_to_now(self, classes_data, instructor_cache):
        """When fetched_at is omitted, the parser fills it in automatically."""
        before = datetime.now(timezone.utc)
        records = parse_classes_into_records(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            credit_hours=4,
            semester_code="202510",
            classes=classes_data["classes"],
            instructor_cache=instructor_cache,
        )
        after = datetime.now(timezone.utc)
        for r in records:
            assert before <= r.fetched_at <= after

    def test_all_records_in_batch_share_fetched_at(self, classes_data, instructor_cache):
        """All records produced from a single parse call share the same fetched_at."""
        records = parse_classes_into_records(
            course_code="CS1428",
            course_name="FOUNDATIONS OF COMPUTER SCI I",
            credit_hours=4,
            semester_code="202510",
            classes=classes_data["classes"],
            instructor_cache=instructor_cache,
        )
        timestamps = {r.fetched_at for r in records}
        assert len(timestamps) == 1, "All records in a batch must share fetched_at"


# ── Extended Validator: format checks ─────────────────────────────────

class TestValidatorFormatChecks:
    """Verify the expanded format-level validation rules."""

    def test_valid_course_code_formats(self):
        for code in ("CS1428", "MATH2471", "PHIL1305", "ENG2254", "COMM1315", "CIS4360"):
            result = validate_batch([_make_record(course_code=code)])
            assert result.ok, f"Expected {code!r} to be valid, got: {result.errors}"

    def test_invalid_course_code_lowercase(self):
        result = validate_batch([_make_record(course_code="cs1428")])
        assert not result.ok
        assert "course_code" in result.errors[0][1]

    def test_invalid_course_code_no_digits(self):
        result = validate_batch([_make_record(course_code="CSHELLO")])
        assert not result.ok
        assert "course_code" in result.errors[0][1]

    def test_invalid_course_code_too_short_prefix(self):
        result = validate_batch([_make_record(course_code="C1428")])
        assert not result.ok

    def test_valid_semester_codes(self):
        for code in ("202510", "202530", "202550", "202506", "202507", "202512", "202505"):
            result = validate_batch([_make_record(semester_code=code)])
            assert result.ok, f"Expected {code!r} to be valid, got: {result.errors}"

    def test_invalid_semester_code_bad_month(self):
        result = validate_batch([_make_record(semester_code="202599")])
        assert not result.ok
        assert "semester_code" in result.errors[0][1]

    def test_invalid_semester_code_too_short(self):
        result = validate_batch([_make_record(semester_code="20251")])
        assert not result.ok

    def test_valid_https_url(self):
        result = validate_batch([_make_record(
            source_url="https://api.hb2504.txst.edu/py/getsyllabus.py?class=12345"
        )])
        assert result.ok

    def test_invalid_http_url(self):
        result = validate_batch([_make_record(
            source_url="http://api.hb2504.txst.edu/py/getsyllabus.py?class=12345"
        )])
        assert not result.ok
        assert "source_url" in result.errors[0][1]

    def test_invalid_relative_url(self):
        result = validate_batch([_make_record(source_url="/getsyllabus.py?class=12345")])
        assert not result.ok
        assert "source_url" in result.errors[0][1]

    def test_has_syllabus_false_still_valid(self):
        """has_syllabus=False rows must pass validation — no-syllabus sections
        are explicitly tracked and stored in the database."""
        result = validate_batch([_make_record(has_syllabus=False)])
        assert result.ok
        assert len(result.valid) == 1

    def test_multiple_format_errors_reported_together(self):
        """All format errors on a single record should be reported together."""
        result = validate_batch([_make_record(
            course_code="bad",
            semester_code="202599",
            source_url="http://insecure.example.com",
        )])
        assert not result.ok
        err_msg = result.errors[0][1]
        assert "course_code" in err_msg
        assert "semester_code" in err_msg
        assert "source_url" in err_msg


# ── CLI: --fail-on-fetch-errors & --probe-syllabi ─────────────────────

class TestCLIFlags:
    """Verify the new CLI flags without hitting the network."""

    def test_help_includes_probe_syllabi(self):
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-m", "ingest.syllabus.cli", "--help"],
            capture_output=True, text=True,
            cwd=str(pathlib.Path(__file__).parents[3]),
        )
        assert "--probe-syllabi" in result.stdout

    def test_help_includes_fail_on_fetch_errors(self):
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-m", "ingest.syllabus.cli", "--help"],
            capture_output=True, text=True,
            cwd=str(pathlib.Path(__file__).parents[3]),
        )
        assert "--fail-on-fetch-errors" in result.stdout

    def test_pipeline_aborts_on_fetch_errors_with_strict_flag(self):
        """With fail_on_fetch_errors=True, the pipeline returns exit code 1
        when fetch errors occurred, before any writes."""
        from ingest.syllabus.cli import _run_pipeline

        # Patch fetcher to raise on course list fetch
        with patch("ingest.syllabus.cli.HB2504Fetcher") as MockFetcher:
            mock_instance = MockFetcher.return_value
            mock_instance.fetch_cs_courses.return_value = [
                {"number": "CS1428", "title": "FOUNDATIONS OF COMPUTER SCI I"},
            ]
            mock_instance.fetch_course_details.side_effect = OSError("network down")

            exit_code = _run_pipeline(
                apply=False,
                database_url=None,
                max_semesters=1,
                probe_syllabi=False,
                fail_on_fetch_errors=True,
                verbose=False,
                catalog_year=None,
            )
        assert exit_code == 1

    def test_pipeline_continues_on_fetch_errors_without_strict_flag(self):
        """Without fail_on_fetch_errors, the pipeline returns 0 even with errors."""
        from ingest.syllabus.cli import _run_pipeline

        with patch("ingest.syllabus.cli.HB2504Fetcher") as MockFetcher:
            mock_instance = MockFetcher.return_value
            mock_instance.fetch_cs_courses.return_value = [
                {"number": "CS1428", "title": "FOUNDATIONS OF COMPUTER SCI I"},
            ]
            mock_instance.fetch_course_details.side_effect = OSError("network down")

            exit_code = _run_pipeline(
                apply=False,
                database_url=None,
                max_semesters=1,
                probe_syllabi=False,
                fail_on_fetch_errors=False,
                verbose=False,
                catalog_year=None,
            )
        assert exit_code == 0
