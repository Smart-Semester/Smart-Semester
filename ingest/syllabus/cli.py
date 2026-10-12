"""CLI entry-point for the syllabus ingest pipeline.

Usage:
    # Dry-run preview (default — no database writes)
    python -m ingest.syllabus.cli

    # Apply to database
    DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \
        python -m ingest.syllabus.cli --apply

    # Limit semesters fetched per course (faster for testing)
    python -m ingest.syllabus.cli --max-semesters 2
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

from .fetcher import HB2504Fetcher
from .models import SyllabusRecord
from .parser import parse_classes_into_records
from .validator import validate_batch
from .loader import load_records

logger = logging.getLogger("ingest.syllabus")

LISTING_PAGE_URL = "https://hb2504.txst.edu/browsecourses.html#CS"


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _run_pipeline(
    *,
    apply: bool,
    database_url: str | None,
    max_semesters: int | None,
    probe_syllabi: bool,
    verbose: bool,
) -> int:
    """Run the full ingest pipeline.  Returns exit code."""
    _configure_logging(verbose)

    logger.info("Starting syllabus ingest from %s", LISTING_PAGE_URL)

    # ------------------------------------------------------------------
    # Step 1: Fetch course listing
    # ------------------------------------------------------------------
    fetcher = HB2504Fetcher()
    logger.info("Fetching CS course list...")
    try:
        courses = fetcher.fetch_cs_courses()
    except Exception as exc:
        logger.error("Failed to fetch CS course list: %s", exc)
        return 1

    logger.info("Found %d CS courses.", len(courses))

    # ------------------------------------------------------------------
    # Step 2: For each course, fetch semesters and class sections
    # ------------------------------------------------------------------
    all_records: list[SyllabusRecord] = []
    instructor_cache: dict[str, str] = {}  # plid → display name
    fetch_errors: list[str] = []

    for ci, course in enumerate(courses, 1):
        code = course["number"]
        title = course["title"]
        logger.info("[%d/%d] Fetching details for %s ...", ci, len(courses), code)

        try:
            details = fetcher.fetch_course_details(code)
        except Exception as exc:
            msg = f"Failed to fetch details for {code}: {exc}"
            logger.warning(msg)
            fetch_errors.append(msg)
            continue

        credit_hours = details.get("credit_hours")
        semesters = details.get("semesters", [])

        if max_semesters is not None:
            semesters = semesters[:max_semesters]

        for sem in semesters:
            sem_str = str(sem)
            try:
                classes = fetcher.fetch_classes(code, sem_str)
            except Exception as exc:
                msg = f"Failed to fetch classes for {code}/{sem_str}: {exc}"
                logger.warning(msg)
                fetch_errors.append(msg)
                continue

            # Resolve unknown instructors
            for cls in classes:
                for inst in cls.get("instructors", []):
                    plid = inst.get("hplid")
                    if plid and plid not in instructor_cache:
                        try:
                            info = fetcher.fetch_instructor(plid)
                            instructor_cache[plid] = info.get("displayname", "")
                        except Exception:
                            logger.debug("Could not fetch instructor %s", plid)
                            instructor_cache[plid] = ""  # cache the miss

            records = parse_classes_into_records(
                course_code=code,
                course_name=title,
                credit_hours=credit_hours,
                semester_code=sem_str,
                classes=classes,
                instructor_cache=instructor_cache,
            )
            all_records.extend(records)

    logger.info(
        "Fetched %d total syllabus entries across %d courses.",
        len(all_records),
        len(courses),
    )
    if fetch_errors:
        logger.warning("%d fetch errors occurred:", len(fetch_errors))
        for err in fetch_errors:
            logger.warning("  • %s", err)

    # ------------------------------------------------------------------
    # Step 3: Validate
    # ------------------------------------------------------------------
    result = validate_batch(all_records)
    print("\n" + result.summary())

    # ------------------------------------------------------------------
    # Step 4: Preview or apply
    # ------------------------------------------------------------------
    if not apply:
        print("\n=== DRY-RUN PREVIEW (first 10 records) ===")
        for rec in result.valid[:10]:
            print(
                f"  {rec.course_code} §{rec.section}  {rec.semester:15s}"
                f"  instructor={rec.instructor_name or '(unknown)'}"
                f"  syllabus={'YES' if rec.has_syllabus else 'no'}"
                f"  url={rec.source_url}"
            )
        if len(result.valid) > 10:
            print(f"  ... and {len(result.valid) - 10} more.")

        print(
            f"\nTotal valid records: {len(result.valid)}"
            f"  |  Errors: {len(result.errors)}"
            f"  |  Fetch errors: {len(fetch_errors)}"
        )
        print("\nRe-run with --apply to write to the database.")
        return 0

    # Apply mode
    if not database_url:
        logger.error(
            "--apply requires DATABASE_URL environment variable to be set."
        )
        return 1

    if not result.valid:
        logger.error("No valid records to write.")
        return 1

    try:
        count = load_records(result.valid, database_url)
        print(f"\nSuccessfully upserted {count} syllabus records.")
        return 0
    except Exception as exc:
        logger.error("Apply failed: %s", exc)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest CS syllabi from the TXST HB 2504 site.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write records to Postgres (default is dry-run preview).",
    )
    parser.add_argument(
        "--max-semesters",
        type=int,
        default=None,
        help="Limit the number of semesters fetched per course (for testing).",
    )
    parser.add_argument(
        "--probe-syllabi",
        action="store_true",
        default=False,
        help="HEAD each syllabus URL to discover content-type and filename (slow).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable debug logging.",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if args.apply and not database_url:
        print(
            "ERROR: --apply requires the DATABASE_URL environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    exit_code = _run_pipeline(
        apply=args.apply,
        database_url=database_url,
        max_semesters=args.max_semesters,
        probe_syllabi=args.probe_syllabi,
        verbose=args.verbose,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
