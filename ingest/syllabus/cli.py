"""CLI entry-point for the syllabus ingest pipeline.

Pipeline boundary
-----------------
This pipeline fetches CS course listings, available semesters, class sections,
and instructor metadata from the TXST HB 2504 API, then upserts syllabus
listing metadata (including has_syllabus=False rows) into the database.

It does NOT download syllabus PDFs or extract syllabus text. PDF download and
text extraction are reserved for a later phase (see checklist section 6).

Usage:
    # Dry-run preview (default — no database writes)
    python -m ingest.syllabus.cli

    # Apply to database
    DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \\
        python -m ingest.syllabus.cli --apply

    # Limit semesters fetched per course (faster for testing)
    python -m ingest.syllabus.cli --max-semesters 2

    # Pass the catalog year for traceability
    python -m ingest.syllabus.cli --catalog-year 2024-2025

    # Probe each syllabus URL for content-type and filename (slow)
    python -m ingest.syllabus.cli --probe-syllabi

    # Fail the run if any fetch errors occur (strict mode)
    python -m ingest.syllabus.cli --apply --fail-on-fetch-errors
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

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


def _probe_syllabus_url(url: str) -> tuple[str | None, str | None]:
    """HEAD the syllabus URL to discover content-type and filename.

    Returns (original_format, syllabus_filename).  Both are None on failure.
    This is intentionally best-effort — a probe failure does not invalidate
    the record; the row is still stored with the metadata fields as None.
    """
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "SmartSemester-Ingest/1.0 (probe)")
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type")
            disposition = resp.headers.get("Content-Disposition", "")
            filename: str | None = None
            if "filename=" in disposition:
                filename = disposition.split("filename=")[-1].strip().strip('"')
            return content_type, filename
    except Exception as exc:
        logger.debug("Probe failed for %s: %s", url, exc)
        return None, None


def _run_pipeline(
    *,
    apply: bool,
    database_url: str | None,
    max_semesters: int | None,
    probe_syllabi: bool,
    fail_on_fetch_errors: bool,
    verbose: bool,
    catalog_year: str | None,
) -> int:
    """Run the full ingest pipeline.  Returns exit code."""
    _configure_logging(verbose)

    logger.info("Starting syllabus ingest from %s", LISTING_PAGE_URL)

    # Capture a single fetch timestamp for the entire run so every record in
    # this ingest batch shares the same fetched_at value.  This makes it easy
    # to identify all rows that came from the same run.
    run_fetched_at = datetime.now(timezone.utc)
    if catalog_year:
        logger.info("Catalog year: %s", catalog_year)
    logger.info("Fetch timestamp (UTC): %s", run_fetched_at.isoformat())

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
                fetched_at=run_fetched_at,
                catalog_year=catalog_year,
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
    # Step 2b (optional): Probe syllabus URLs for content-type/filename
    # ------------------------------------------------------------------
    if probe_syllabi:
        has_syllabus_records = [r for r in all_records if r.has_syllabus]
        logger.info(
            "Probing %d syllabus URLs (this may be slow)...",
            len(has_syllabus_records),
        )
        probed: list[SyllabusRecord] = []
        for rec in all_records:
            if rec.has_syllabus:
                content_type, filename = _probe_syllabus_url(rec.source_url)
                # SyllabusRecord is frozen; rebuild with updated probe fields.
                import dataclasses
                probed.append(dataclasses.replace(
                    rec,
                    original_format=content_type,
                    syllabus_filename=filename,
                ))
            else:
                probed.append(rec)
        all_records = probed
        logger.info("Probe complete.")

    # ------------------------------------------------------------------
    # Step 3: Validate
    # ------------------------------------------------------------------
    result = validate_batch(all_records)
    print("\n" + result.summary())

    # ------------------------------------------------------------------
    # Step 3b: Decide whether fetch errors block --apply
    # ------------------------------------------------------------------
    if fetch_errors and fail_on_fetch_errors:
        logger.error(
            "%d fetch error(s) occurred and --fail-on-fetch-errors is set. "
            "Aborting before any database writes.",
            len(fetch_errors),
        )
        return 1

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

        no_syllabus_count = sum(1 for r in result.valid if not r.has_syllabus)
        print(
            f"\nTotal valid records: {len(result.valid)}"
            f"  |  No-syllabus rows: {no_syllabus_count}"
            f"  |  Errors: {len(result.errors)}"
            f"  |  Fetch errors: {len(fetch_errors)}"
        )
        if fetch_errors and not fail_on_fetch_errors:
            print(
                "NOTE: Fetch errors occurred but --fail-on-fetch-errors was not set. "
                "Re-run with --fail-on-fetch-errors to treat errors as fatal."
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
        no_syllabus_count = sum(1 for r in result.valid if not r.has_syllabus)
        print(f"\nSuccessfully upserted {count} syllabus records.")
        print(
            f"  of which {no_syllabus_count} have has_syllabus=False "
            "(section exists, no syllabus available)."
        )
        if fetch_errors:
            print(
                f"WARNING: {len(fetch_errors)} fetch error(s) occurred during this run. "
                "Some courses or semesters may be missing. See log for details."
            )
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
        help=(
            "HEAD each syllabus URL to discover content-type and filename. "
            "Populates original_format and syllabus_filename on each record. "
            "Slow for large batches; disabled by default."
        ),
    )
    parser.add_argument(
        "--fail-on-fetch-errors",
        action="store_true",
        default=False,
        help=(
            "Abort the run (before any database writes) if any upstream fetch "
            "errors occur. By default the pipeline continues and writes whatever "
            "valid records it collected (partial ingest). Use this flag for "
            "stricter runs where a partial ingest is not acceptable."
        ),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--catalog-year",
        default=None,
        metavar="YEAR",
        help=(
            "Catalog year this ingest run belongs to, e.g. '2024-2025'. "
            "Stored on every row for traceability and refresh decisions."
        ),
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
        fail_on_fetch_errors=args.fail_on_fetch_errors,
        verbose=args.verbose,
        catalog_year=args.catalog_year,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
