"""CLI entry-point for the syllabus ingest pipeline.

Pipeline boundary
-----------------
This pipeline fetches CS course listings, available semesters, class sections,
and instructor metadata from the TXST HB 2504 API, then upserts syllabus
listing metadata (including has_syllabus=False rows) into the database.

When `--download-syllabi` is passed, the pipeline additionally downloads
syllabus PDFs for syllabus-bearing sections, extracts text via pypdf, extracts
structured observations (grading breakdowns, textbooks, topics, workload,
office hours, course policies) into catalog.syllabus_observations with
source-document provenance, and routes unextractable or scanned documents to
a manual review queue.

Usage:
    # Dry-run preview (default — no database writes)
    python -m ingest.syllabus.cli

    # Dry-run preview with syllabus PDF download and extraction
    python -m ingest.syllabus.cli --max-semesters 1 --download-syllabi

    # Apply to database
    DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \\
        python -m ingest.syllabus.cli --apply

    # Apply with syllabus PDF download, extraction, and observation storage
    DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \\
        python -m ingest.syllabus.cli --apply --download-syllabi --catalog-year 2024-2025

    # Force re-download and re-extraction of unchanged documents
    DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \\
        python -m ingest.syllabus.cli --apply --download-syllabi --reprocess

    # Inspect manual review queue for scanned or malformed documents
    DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \\
        python -m ingest.syllabus.cli --list-manual-review

    # Resolve a document in the manual review queue
    DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \\
        python -m ingest.syllabus.cli --resolve-manual-review <DOC_UUID> \\
            --manual-notes "Transcribed via OCR" --manual-text-file path/to/text.txt
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
from pathlib import Path

from .fetcher import HB2504Fetcher
from .models import (
    DownloadStatus,
    ExtractionStatus,
    ObservationRecord,
    SyllabusDocumentRecord,
    SyllabusRecord,
)
from .parser import parse_classes_into_records
from .validator import validate_batch
from .loader import (
    get_document_by_content_hash,
    get_document_by_source_url,
    list_manual_review_documents,
    load_documents_and_observations,
    load_observations,
    load_records,
    resolve_manual_review,
    upsert_syllabus_document,
)
from .downloader import (
    DEFAULT_MAX_PDF_SIZE_BYTES,
    DEFAULT_STORAGE_DIR,
    SyllabusDownloader,
)
from .extractor import PDFTextExtractor
from .observations import ObservationExtractor

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
    download_syllabi: bool = False,
    storage_dir: str | None = None,
    retain_pdf: bool = True,
    max_pdf_size: int = DEFAULT_MAX_PDF_SIZE_BYTES,
    reprocess: bool = False,
    list_manual_review: bool = False,
    resolve_review_id: str | None = None,
    manual_notes: str | None = None,
    manual_text_file: str | None = None,
) -> int:
    """Run the full ingest pipeline.  Returns exit code."""
    _configure_logging(verbose)

    # ── Handle manual review actions first ────────────────────────────
    if list_manual_review:
        if not database_url:
            logger.error("--list-manual-review requires DATABASE_URL.")
            return 1
        items = list_manual_review_documents(database_url)
        print(f"\n=== MANUAL REVIEW QUEUE ({len(items)} items) ===")
        if not items:
            print("  No documents currently require manual review.")
        for it in items:
            print(
                f"  Doc ID: {it['document_id']}\n"
                f"    Course: {it['course_code']} §{it['section']} ({it['semester']})\n"
                f"    Instructor: {it['instructor_name'] or '(unknown)'}\n"
                f"    Download Status: {it['download_status']} | Extraction Status: {it['extraction_status']}\n"
                f"    Reason: {it['manual_review_reason']}\n"
                f"    URL: {it['source_url']}\n"
                f"    File: {it['file_path'] or '(none)'}\n"
            )
        return 0

    if resolve_review_id:
        if not database_url:
            logger.error("--resolve-manual-review requires DATABASE_URL.")
            return 1
        manual_text = None
        if manual_text_file:
            path = Path(manual_text_file)
            if not path.is_file():
                logger.error("Manual text file not found: %s", path)
                return 1
            manual_text = path.read_text(encoding="utf-8")
        ok = resolve_manual_review(
            document_id=resolve_review_id,
            notes=manual_notes or "Resolved via CLI",
            manual_text=manual_text,
            database_url=database_url,
        )
        if ok:
            print(f"Successfully resolved manual review for document {resolve_review_id}")
            return 0
        else:
            logger.error("Document %s not found in manual review queue.", resolve_review_id)
            return 1

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
    # Step 3c (optional): Download syllabus PDFs and extract text
    # ------------------------------------------------------------------
    downloaded_docs: list[tuple[SyllabusDocumentRecord, list[ObservationRecord]]] = []
    skipped_unchanged_count = 0
    if download_syllabi:
        # Select only sections that have a syllabus; preserve sections without
        # a syllabus as metadata records without attempting PDF retrieval.
        has_syllabus_records = [
            r for r in result.valid if r.has_syllabus and bool(r.source_url)
        ]
        logger.info(
            "Downloading and extracting %d syllabus documents (storage_dir=%s)...",
            len(has_syllabus_records),
            storage_dir or DEFAULT_STORAGE_DIR,
        )
        downloader = SyllabusDownloader(
            storage_dir=storage_dir,
            max_size_bytes=max_pdf_size,
            retain_pdf=retain_pdf,
        )
        extractor = PDFTextExtractor()
        obs_extractor = ObservationExtractor()

        for rec in has_syllabus_records:
            existing_doc = None
            if database_url:
                try:
                    existing_doc = get_document_by_source_url(rec.source_url, database_url)
                except Exception:
                    pass

            doc_record, pdf_bytes = downloader.download_document(rec, existing_doc=existing_doc)

            # Change detection: skip unchanged documents based on content hash
            # when previous extraction succeeded, unless --reprocess is passed
            is_unchanged = (
                existing_doc is not None
                and existing_doc.content_hash is not None
                and existing_doc.content_hash == doc_record.content_hash
                and existing_doc.extraction_status == ExtractionStatus.SUCCESS
                and not reprocess
            )

            if is_unchanged:
                logger.info(
                    "Skipping %s (hash %s unchanged; use --reprocess to force)",
                    rec.source_url,
                    doc_record.content_hash,
                )
                skipped_unchanged_count += 1
                continue

            if doc_record.download_status == DownloadStatus.DOWNLOADED and pdf_bytes:
                doc_record = extractor.extract_text(doc_record, pdf_bytes)
                observations = obs_extractor.extract_observations(doc_record, rec)
            else:
                observations = []
            downloaded_docs.append((doc_record, observations))

        logger.info(
            "Processed %d syllabus documents (%d unchanged skipped).",
            len(downloaded_docs),
            skipped_unchanged_count,
        )

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
        if download_syllabi:
            success_count = sum(1 for d, _ in downloaded_docs if d.extraction_status == ExtractionStatus.SUCCESS)
            review_count = sum(1 for d, _ in downloaded_docs if d.manual_review_required)
            total_obs = sum(len(obs) for _, obs in downloaded_docs)
            print(
                f"\nPDF Download & Extraction Preview:\n"
                f"  Processed: {len(downloaded_docs)} documents\n"
                f"  Extraction SUCCESS: {success_count}\n"
                f"  Manual Review Required: {review_count}\n"
                f"  Extracted Observations: {total_obs}"
            )
            if skipped_unchanged_count:
                print(f"  Unchanged Documents Skipped (by hash): {skipped_unchanged_count}")
            for d, obs in downloaded_docs[:3]:
                print(f"  Sample Doc: {d.source_url}")
                print(f"    Status: {d.download_status} / {d.extraction_status}")
                if d.manual_review_required:
                    print(f"    Manual Review Reason: {d.manual_review_reason}")
                if obs:
                    print(f"    Observations ({len(obs)}):")
                    for o in obs[:3]:
                        print(f"      [{o.category}] {o.observation_key}: {o.observation_value}")
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

        if download_syllabi:
            if downloaded_docs:
                docs_upserted, obs_total = load_documents_and_observations(
                    downloaded_docs, database_url
                )
                print(
                    f"Successfully upserted {docs_upserted} syllabus documents and "
                    f"{obs_total} structured observations."
                )
            if skipped_unchanged_count:
                print(
                    f"  ({skipped_unchanged_count} unchanged documents skipped based on content hash; "
                    "use --reprocess to force overwrite)."
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
    # ── Section 6: PDF download, extraction, and manual review ────────
    parser.add_argument(
        "--download-syllabi",
        action="store_true",
        default=False,
        help=(
            "Download syllabus PDFs and extract text and structured observations "
            "for sections with has_syllabus=True."
        ),
    )
    parser.add_argument(
        "--storage-dir",
        default=None,
        metavar="DIR",
        help=(
            "Directory to retain downloaded PDF documents (default: 'data/syllabi' "
            "or SYLLABUS_STORAGE_DIR env var)."
        ),
    )
    parser.add_argument(
        "--no-retain-pdf",
        action="store_true",
        default=False,
        help="Do not retain raw PDF files on disk after extraction (saves disk storage).",
    )
    parser.add_argument(
        "--max-pdf-size",
        type=int,
        default=DEFAULT_MAX_PDF_SIZE_BYTES,
        metavar="BYTES",
        help=f"Maximum allowed PDF size in bytes (default: {DEFAULT_MAX_PDF_SIZE_BYTES} = 10 MB).",
    )
    parser.add_argument(
        "--reprocess",
        action="store_true",
        default=False,
        help="Force re-download and re-extraction of PDFs even if unchanged.",
    )
    parser.add_argument(
        "--list-manual-review",
        action="store_true",
        default=False,
        help="List documents currently requiring manual review.",
    )
    parser.add_argument(
        "--resolve-manual-review",
        metavar="DOC_ID",
        default=None,
        help="Resolve a document in the manual review queue by its UUID.",
    )
    parser.add_argument(
        "--manual-notes",
        metavar="NOTES",
        default=None,
        help="Notes explaining the manual review resolution.",
    )
    parser.add_argument(
        "--manual-text-file",
        metavar="FILE",
        default=None,
        help="Path to a text file containing manually transcribed syllabus text.",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    needs_db = args.apply or args.list_manual_review or args.resolve_manual_review
    if needs_db and not database_url:
        print(
            "ERROR: This action requires the DATABASE_URL environment variable.",
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
        download_syllabi=args.download_syllabi,
        storage_dir=args.storage_dir,
        retain_pdf=not args.no_retain_pdf,
        max_pdf_size=args.max_pdf_size,
        reprocess=args.reprocess,
        list_manual_review=args.list_manual_review,
        resolve_review_id=args.resolve_manual_review,
        manual_notes=args.manual_notes,
        manual_text_file=args.manual_text_file,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
