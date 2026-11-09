"""Fetcher — talks to the HB 2504 JSON API to discover CS syllabi.

The API is at https://api.hb2504.txst.edu/py/ and uses simple GET
requests returning JSON (despite the server-side .py extension).

The pipeline walks:
  1. getcoursesfordepartment.py?department=CS  → list of courses
  2. getcoursedetails.py?course=<code>         → semesters + metadata
  3. getclassesforcourse.py?course=<code>&semester=<sem> → class sections
  4. getinstructordetails.py?plid=<id>         → instructor name

Rate limiting: 0.25 s delay between requests by default.

Retry policy: transient HTTP errors (429, 5xx) and network errors are
retried up to MAX_RETRIES times with exponential backoff starting at
BACKOFF_BASE seconds.  A ``Retry-After`` response header is respected
when present on 429 responses.
"""
from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
import json
from typing import Any, Optional
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

API_BASE = "https://api.hb2504.txst.edu/py"
USER_AGENT = "SmartSemester-Bot/1.0 (university capstone project)"
DEFAULT_DELAY = 0.25  # seconds between requests
TIMEOUT = 15  # seconds

# Retry / backoff settings
MAX_RETRIES = 3          # attempts after the first failure (total = 4 tries)
BACKOFF_BASE = 1.0       # seconds for first retry; doubles each attempt
BACKOFF_MAX = 30.0       # cap on any single sleep
# HTTP status codes that are worth retrying (server-side / rate-limit errors)
_RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

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
        max_retries: int = MAX_RETRIES,
        backoff_base: float = BACKOFF_BASE,
        backoff_max: float = BACKOFF_MAX,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._delay = delay
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._last_request: float = 0.0

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)

    @staticmethod
    def _retry_after(exc: urllib.error.HTTPError) -> float | None:
        """Parse the Retry-After header from a 429 response, if present.

        Returns the number of seconds to wait, or None if the header is
        absent or unparseable.
        """
        raw = exc.headers.get("Retry-After") if exc.headers else None
        if raw is None:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            return None

    def _get_json(self, endpoint: str, params: dict[str, str] | None = None) -> Any:
        """GET *endpoint* and return parsed JSON.

        Retries up to ``self._max_retries`` times on transient HTTP errors
        (429, 5xx) and network-level errors, using exponential backoff.
        A ``Retry-After`` header on 429 responses is respected.

        Raises the last exception if all attempts fail.
        """
        url = f"{self._api_base}/{endpoint}"
        if params:
            url += "?" + urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            self._throttle()
            logger.debug("GET %s (attempt %d/%d)", url, attempt + 1, self._max_retries + 1)
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    self._last_request = time.monotonic()
                    return json.loads(resp.read().decode())

            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code not in _RETRYABLE_STATUSES or attempt >= self._max_retries:
                    logger.error(
                        "HTTP %d fetching %s — not retrying (attempt %d/%d)",
                        exc.code, url, attempt + 1, self._max_retries + 1,
                    )
                    raise

                # Respect Retry-After on 429, otherwise use exponential backoff
                if exc.code == 429:
                    wait = self._retry_after(exc)
                    if wait is not None:
                        logger.warning(
                            "HTTP 429 — Retry-After: %.1f s (attempt %d/%d)",
                            wait, attempt + 1, self._max_retries + 1,
                        )
                    else:
                        wait = min(self._backoff_base * (2 ** attempt), self._backoff_max)
                        logger.warning(
                            "HTTP 429 — backing off %.1f s (attempt %d/%d)",
                            wait, attempt + 1, self._max_retries + 1,
                        )
                else:
                    wait = min(self._backoff_base * (2 ** attempt), self._backoff_max)
                    logger.warning(
                        "HTTP %d — backing off %.1f s (attempt %d/%d)",
                        exc.code, wait, attempt + 1, self._max_retries + 1,
                    )
                time.sleep(wait)

            except OSError as exc:
                # Covers socket timeouts, connection refused, DNS failures, etc.
                last_exc = exc
                if attempt >= self._max_retries:
                    logger.error(
                        "Network error fetching %s — giving up after %d attempts: %s",
                        url, self._max_retries + 1, exc,
                    )
                    raise
                wait = min(self._backoff_base * (2 ** attempt), self._backoff_max)
                logger.warning(
                    "Network error fetching %s — backing off %.1f s (attempt %d/%d): %s",
                    url, wait, attempt + 1, self._max_retries + 1, exc,
                )
                time.sleep(wait)

        # Should be unreachable, but keeps the type-checker happy
        raise RuntimeError(f"Exhausted retries for {url}") from last_exc

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
