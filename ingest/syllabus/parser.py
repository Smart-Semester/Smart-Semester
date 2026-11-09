"""Parser — converts raw API responses into SyllabusRecord objects.

This module is intentionally separate from the fetcher so that it can be
tested entirely offline with saved fixture data.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .fetcher import semester_to_label
from .models import SyllabusRecord

logger = logging.getLogger(__name__)

API_BASE_DEFAULT = "https://api.hb2504.txst.edu/py"
SOURCE_HOST_DEFAULT = "api.hb2504.txst.edu"


def build_syllabus_url(api_base: str, index_num: int) -> str:
    return f"{api_base}/getsyllabus.py?class={index_num}"


def parse_classes_into_records(
    *,
    course_code: str,
    course_name: str,
    credit_hours: Optional[int],
    semester_code: str,
    classes: list[dict[str, Any]],
    instructor_cache: dict[str, str],
    api_base: str = API_BASE_DEFAULT,
    fetched_at: Optional[datetime] = None,
    catalog_year: Optional[str] = None,
    source_host: str = SOURCE_HOST_DEFAULT,
) -> list[SyllabusRecord]:
    """Parse the raw 'classes' list for one course+semester into records.

    Parameters
    ----------
    course_code : e.g. "CS1428"
    course_name : e.g. "FOUNDATIONS OF COMPUTER SCI I"
    credit_hours : from course details (may be None)
    semester_code : raw API code, e.g. "202510"
    classes : the 'classes' array from getclassesforcourse.py
    instructor_cache : mapping plid → display name (may be incomplete)
    api_base : API base URL for building syllabus URLs
    fetched_at : UTC timestamp of the upstream API call; defaults to now
    catalog_year : academic year, e.g. "2024-2025"; None if not known
    source_host : hostname of the upstream API, e.g. "api.hb2504.txst.edu"
    """
    if fetched_at is None:
        fetched_at = datetime.now(timezone.utc)

    semester_label = semester_to_label(semester_code)
    records: list[SyllabusRecord] = []

    for cls in classes:
        index_num = cls.get("indexnum")
        if index_num is None:
            logger.warning(
                "Skipping class with no indexnum: course=%s semester=%s",
                course_code,
                semester_code,
            )
            continue

        section = cls.get("section", "???")
        has_syllabus = bool(cls.get("syllabus", False))

        # Pick the first instructor (most classes have exactly one)
        instructors = cls.get("instructors", [])
        plid: Optional[str] = None
        instructor_name: Optional[str] = None
        if instructors:
            plid = instructors[0].get("hplid")
            if plid and plid in instructor_cache:
                instructor_name = instructor_cache[plid]

        source_url = build_syllabus_url(api_base, index_num)

        records.append(
            SyllabusRecord(
                course_code=course_code,
                course_name=course_name,
                section=section,
                semester=semester_label,
                semester_code=semester_code,
                instructor_name=instructor_name,
                instructor_plid=plid,
                source_url=source_url,
                has_syllabus=has_syllabus,
                original_format=None,  # filled later by probe
                syllabus_filename=None,  # filled later by probe
                credit_hours=credit_hours,
                index_num=index_num,
                fetched_at=fetched_at,
                catalog_year=catalog_year,
                source_host=source_host,
            )
        )

    return records
