"""Fetcher — talks to the HB 2504 JSON API to discover CS syllabi.

The API is at https://api.hb2504.txst.edu/py/ and uses simple GET
requests returning JSON (despite the server-side .py extension).

The pipeline walks:
  1. getcoursesfordepartment.py?department=CS  → list of courses
  2. getcoursedetails.py?course=<code>         → semesters + metadata
  3. getclassesforcourse.py?course=<code>&semester=<sem> → class sections
  4. getinstructordetails.py?plid=<id>         → instructor name

Rate limiting: 0.25 s delay between requests by default.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional
from urllib.parse import urlencode

import urllib.request
import json

logger = logging.getLogger(__name__)

API_BASE = "https://api.hb2504.txst.edu/py"
USER_AGENT = "SmartSemester-Bot/1.0 (university capstone project)"
DEFAULT_DELAY = 0.25  # seconds between requests
TIMEOUT = 15  # seconds

# Semester code → human-readable name mapping
# Ported from the site's semesternametranslate() JS function.
_MONTH_NAMES: dict[str, str] = {
    "30": "Spring",
    "05": "Spring",
    "50": "Summer",
    "06": "Summer",
    "07": "Summer I",
    "08": "Summer II",
    "10": "Fall",
    "12": "Fall",
}


def semester_to_label(code: str) -> str:
    """Convert an API semester code like '202510' to 'Fall 2024'.

    The encoding is YYYYMM where:
    - For codes after 2011 with month '07', treat as '06' (Summer).
    - For month '10', the year is decremented (Fall of previous academic year).
    """
    year_s = code[:4]
    month = code[4:]
    year = int(year_s)

    if year > 2011 and month == "07":
        month = "06"
    if month == "10":
        year -= 1

    name = _MONTH_NAMES.get(month, f"Unknown({month})")
    return f"{name} {year}"


class HB2504Fetcher:
    """Fetches syllabus listing data from the HB 2504 API."""

    def __init__(
        self,
        *,
        api_base: str = API_BASE,
        delay: float = DEFAULT_DELAY,
        timeout: int = TIMEOUT,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._delay = delay
        self._timeout = timeout
        self._last_request: float = 0.0

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)

    def _get_json(self, endpoint: str, params: dict[str, str] | None = None) -> Any:
        """GET *endpoint* and return parsed JSON."""
        self._throttle()
        url = f"{self._api_base}/{endpoint}"
        if params:
            url += "?" + urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        logger.debug("GET %s", url)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                self._last_request = time.monotonic()
                return json.loads(resp.read().decode())
        except Exception:
            logger.exception("Failed to fetch %s", url)
            raise

    def _head_syllabus(self, index_num: int) -> tuple[Optional[str], Optional[str]]:
        """HEAD the syllabus download URL, return (content_type, filename)."""
        self._throttle()
        url = f"{self._api_base}/getsyllabus.py?class={index_num}"
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        logger.debug("HEAD %s", url)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                self._last_request = time.monotonic()
                ct = resp.headers.get("Content-Type")
                cd = resp.headers.get("Content-Disposition", "")
                filename = None
                if 'filename="' in cd:
                    filename = cd.split('filename="')[1].rstrip('"')
                elif "filename=" in cd:
                    filename = cd.split("filename=")[1].strip()
                return ct, filename
        except Exception:
            logger.warning("HEAD failed for index_num=%s", index_num)
            return None, None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_cs_courses(self) -> list[dict[str, str]]:
        """Return the list of CS courses: [{number, title}, ...]."""
        data = self._get_json("getcoursesfordepartment.py", {"department": "CS"})
        return data["courses"]

    def fetch_course_details(self, course_code: str) -> dict[str, Any]:
        """Return course details: {credit_hours, semesters, title}."""
        return self._get_json("getcoursedetails.py", {"course": course_code})

    def fetch_classes(self, course_code: str, semester: str) -> list[dict[str, Any]]:
        """Return class sections for a course+semester."""
        data = self._get_json(
            "getclassesforcourse.py",
            {"course": course_code, "semester": semester},
        )
        return data.get("classes", [])

    def fetch_instructor(self, plid: str) -> dict[str, Any]:
        """Return instructor details: {displayname, netid, title, ...}."""
        return self._get_json("getinstructordetails.py", {"plid": plid})

    def syllabus_url(self, index_num: int) -> str:
        """Build the canonical syllabus download URL."""
        return f"{self._api_base}/getsyllabus.py?class={index_num}"

    def probe_syllabus(self, index_num: int) -> tuple[Optional[str], Optional[str]]:
        """Probe a syllabus to learn its content-type and filename."""
        return self._head_syllabus(index_num)
