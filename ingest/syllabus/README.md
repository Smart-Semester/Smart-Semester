# Syllabus Ingest Pipeline

Ingests CS course syllabi from the [TXST HB 2504 site](https://hb2504.txst.edu/browsecourses.html#CS) into the Smart Semester database.

## Pipeline Boundary

This pipeline covers:
- CS course listings (all courses in the department)
- Available semesters and class sections per course
- Instructor metadata (resolved by PLID)
- Syllabus listing metadata — including sections where `has_syllabus=False`
- **PDF Download & Text Extraction (Phase 8)**: Optional downloading of syllabus PDFs with integrity/size checks, text extraction via `pypdf`, structured observation extraction with source provenance, and an explicit manual-review queue for unextractable/scanned documents.

By default, metadata ingest does not download PDFs unless the `--download-syllabi` flag is provided. Dry-run preview is the default; `--apply` is required for database writes.

## How It Works

The HB 2504 site exposes a JSON API at `https://api.hb2504.txst.edu/py/`. The pipeline walks through four API endpoints in sequence:

```
getcoursesfordepartment.py?department=CS
  └── For each course:
      getcoursedetails.py?course=CS1428
        └── For each semester:
            getclassesforcourse.py?course=CS1428&semester=202510
              └── For each instructor:
                  getinstructordetails.py?plid=x9028bf7ba7de
```

When `--download-syllabi` is passed, the pipeline additionally:
1. Downloads syllabus PDFs via `downloader.py` (streaming with SHA-256 integrity and 10 MB limit enforcement).
2. Extracts text via `extractor.py` using `pypdf`, detecting scanned/image-only or malformed documents.
3. Routes failures to an explicit manual review queue in `catalog.syllabus_documents`.
4. Extracts structured observations (grading breakdown, textbooks, topics, workload, policies) via `observations.py` with source-document provenance into `catalog.syllabus_observations`.

Each class section produces one `SyllabusRecord` with:
- Course code and name
- Section number
- Semester (human-readable + raw code)
- Instructor name (if resolvable)
- Canonical syllabus download URL (used as the uniqueness key)
- Whether a syllabus document exists (`has_syllabus` flag)

### No-syllabus sections

Sections where `has_syllabus=False` are **valid records** and are stored in the database. The absence of a syllabus is meaningful data — downstream tools use it to tell students that no syllabus is available for a section. These rows are not filtered out by the validator.

### Pipeline Steps

| Step | Module | Description |
|------|--------|-------------|
| 1. Fetch | `fetcher.py` | Talks to the HB 2504 API with rate limiting (0.25s between requests) |
| 2. Parse | `parser.py` | Converts raw API JSON into `SyllabusRecord` dataclasses |
| 3. Validate | `validator.py` | Checks required fields, format (course code, semester code, URL), and duplicates |
| 4. Download (optional) | `downloader.py` | Streams syllabus PDFs with SHA-256 integrity, Content-Type check, and 10 MB limit |
| 5. Extract (optional) | `extractor.py` | Extracts text with `pypdf`, detecting scanned and malformed PDFs |
| 6. Observe (optional) | `observations.py` | Extracts structured observations with snippet provenance |
| 7. Load | `loader.py` | Upserts syllabi, documents, and observations in transactions |

## Quick Start

### Run Tests (offline, no database needed)

```bash
cd /path/to/Smart-Semester
python -m pytest ingest/syllabus/tests/ -v
```

### Dry-Run Preview (hits the live API, does NOT write to database)

```bash
# Preview CS courses and class sections
python -m ingest.syllabus.cli --max-semesters 1

# Preview including PDF download, text extraction, and observation extraction
python -m ingest.syllabus.cli --max-semesters 1 --download-syllabi
```

### Apply to Database

```bash
# 1. Make sure Postgres is running
docker compose up -d db

# 2. Apply all migrations (01 through 06)
python init-db/migrate.py postgresql://postgres:postgrespassword@localhost:5432/smart_semester

# 3. Run metadata ingestion with --apply
DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \
    python -m ingest.syllabus.cli --apply --catalog-year 2024-2025

# 4. Ingest metadata AND download/extract syllabus PDFs + observations
DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \
    python -m ingest.syllabus.cli --apply --download-syllabi --catalog-year 2024-2025

# 5. Inspect manual review queue for scanned or malformed documents
DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \
    python -m ingest.syllabus.cli --list-manual-review
```

## CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--apply` | off | Write records to Postgres (default is dry-run) |
| `--catalog-year YEAR` | None | Tag all rows with a catalog year, e.g. `2024-2025` |
| `--max-semesters N` | all | Limit semesters per course (useful for testing) |
| `--probe-syllabi` | off | HEAD each syllabus URL to discover content-type and filename |
| `--download-syllabi` | off | Download PDFs, extract text, and extract observations |
| `--storage-dir DIR` | `data/syllabi` | Filesystem directory to retain downloaded PDFs |
| `--no-retain-pdf` | off | Discard PDF files on disk after text extraction |
| `--max-pdf-size BYTES`| 10485760 (10 MB)| Maximum allowed size for a single syllabus PDF |
| `--reprocess` | off | Force re-download and re-extraction even if content hash unchanged |
| `--list-manual-review`| off | List documents flagged for manual review |
| `--resolve-manual-review ID` | None | Resolve a document in manual review by document UUID |
| `--manual-notes NOTES`| None | Explanation notes for manual review resolution |
| `--manual-text-file FILE` | None | Text file with transcribed syllabus text |
| `--fail-on-fetch-errors` | off | Abort before writes if any upstream fetch errors occur |
| `--verbose` / `-v` | off | Enable debug logging |

## Fetch Error Policy

By default the pipeline uses **partial ingest**: if individual course or semester fetches fail, the error is logged and the pipeline continues with whatever valid records it collected. This is logged clearly in the output summary.

To require a clean run (no errors allowed), use `--fail-on-fetch-errors`. The pipeline will abort **before any database writes** if errors occurred.

## Safety Guarantees

- **Default is dry-run**: No `--apply` flag = no database writes
- **`DATABASE_URL` required**: Never hardcoded; must be set as an environment variable
- **Transactional writes**: Writes occur within database transactions
- **Upsert on uniqueness keys**: Re-running the importer updates existing records, never creates duplicates
- **Never truncates**: Existing data is preserved
- **Validation before writing**: All records are validated; errors are reported before any writes
- **Separation of observations**: Syllabus-extracted findings are stored in `catalog.syllabus_observations` and never overwrite official `catalog.courses` descriptions or requirements
- **Explicit manual review**: Scanned and malformed documents are routed to a manual review queue instead of silently becoming empty strings

## Database Migration

Versioned migrations in `init-db/` are the authoritative schema source. See [`init-db/migrate.py`](../init-db/migrate.py) for a runner that applies all migrations in order.

| File | What it adds |
|------|-------------|
| `01-init.sql` | `catalog.courses`, `resources.summaries`, `resources.links` |
| `02-syllabi.sql` | `catalog.syllabi` table + indexes |
| `03-traceability.sql` | `fetched_at`, `catalog_year`, `source_host` columns |
| `04-req-tree.sql` | `prereq_tree`, `coreq_tree` JSONB + `requirements_parsed` |
| `05-uniqueness-and-fk.sql` | `UNIQUE(course_code, catalog_year)` + composite lookup index |
| `06-syllabus-documents-and-observations.sql` | `catalog.syllabus_documents` & `catalog.syllabus_observations` |

> **Important:** Docker's `init-db/` scripts only run when a database volume is first created. For existing volumes, apply migrations with `python init-db/migrate.py`.

## Semester Code Encoding

The API uses `YYYYMM` codes mapped as follows (ported from the site's JavaScript):

| Code suffix | Semester | Year adjustment |
|-------------|----------|-----------------|
| `30` or `05` | Spring | None |
| `50`, `06`, `07`* | Summer | None |
| `10` or `12` | Fall | Year decremented |

\* After 2011, code `07` is treated as `06` (Summer).

Example: `202510` → Fall 2024 (year 2025 decremented for month 10).

## Limitations & Best Practices

- **Scanned Syllabi**: Syllabi uploaded as scanned images have no text layer. These are flagged as `SCANNED_NEEDS_OCR` and routed to `--list-manual-review` rather than silently treated as empty text.
- **Instructor names require an extra API call per unique instructor.** The pipeline caches these to minimize requests.
- **The `--probe-syllabi` flag** sends a HEAD request per `has_syllabus=True` record and is slow for large batches. It is best-effort — a probe failure does not invalidate the record.
- **robots.txt**: The HB 2504 site returns 404 for `/robots.txt` (no restrictions). The pipeline uses a descriptive User-Agent and rate limiting regardless.
