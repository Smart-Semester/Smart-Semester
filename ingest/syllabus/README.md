# Syllabus Ingest Pipeline

Ingests CS course syllabi from the [TXST HB 2504 site](https://hb2504.txst.edu/browsecourses.html#CS) into the Smart Semester database.

## Pipeline Boundary

This pipeline covers:
- CS course listings (all courses in the department)
- Available semesters and class sections per course
- Instructor metadata (resolved by PLID)
- Syllabus listing metadata — including sections where `has_syllabus=False`

It does **not** download syllabus PDFs or extract syllabus text. PDF download and text extraction are a later phase (see checklist section 6).

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
| 4. Load | `loader.py` | Upserts to Postgres via `INSERT ... ON CONFLICT` in a transaction |

## Quick Start

### Run Tests (offline, no database needed)

```bash
cd /path/to/Smart-Semester
python -m pytest ingest/syllabus/tests/test_syllabus_ingest.py -v
```

### Dry-Run Preview (hits the live API, does NOT write to database)

```bash
# Preview all courses and semesters
python -m ingest.syllabus.cli

# Preview with only the 2 most recent semesters per course (faster)
python -m ingest.syllabus.cli --max-semesters 2

# Verbose output
python -m ingest.syllabus.cli --max-semesters 1 -v

# Probe each syllabus URL for content-type and filename
python -m ingest.syllabus.cli --max-semesters 1 --probe-syllabi
```

### Apply to Database

```bash
# 1. Make sure Postgres is running
docker compose up -d db

# 2. Apply all migrations (fresh volume: auto-applied; existing volume: run manually)
for f in init-db/*.sql; do
  docker exec -i smart_semester_db psql -U postgres -d smart_semester < "$f"
done

# 3. Run the importer with --apply
DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \
    python -m ingest.syllabus.cli --apply --catalog-year 2024-2025

# 4. (Strict mode) Abort if any fetch errors occur instead of partial ingest
DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \
    python -m ingest.syllabus.cli --apply --fail-on-fetch-errors
```

## CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--apply` | off | Write records to Postgres (default is dry-run) |
| `--catalog-year YEAR` | None | Tag all rows with a catalog year, e.g. `2024-2025` |
| `--max-semesters N` | all | Limit semesters per course (useful for testing) |
| `--probe-syllabi` | off | HEAD each syllabus URL to discover content-type and filename |
| `--fail-on-fetch-errors` | off | Abort before writes if any upstream fetch errors occur |
| `--verbose` / `-v` | off | Enable debug logging |

## Fetch Error Policy

By default the pipeline uses **partial ingest**: if individual course or semester fetches fail, the error is logged and the pipeline continues with whatever valid records it collected. This is logged clearly in the output summary.

To require a clean run (no errors allowed), use `--fail-on-fetch-errors`. The pipeline will abort **before any database writes** if errors occurred.

## Safety Guarantees

- **Default is dry-run**: No `--apply` flag = no database writes
- **`DATABASE_URL` required**: Never hardcoded; must be set as an environment variable
- **Transactional writes**: The entire batch is written in a single transaction
- **Upsert on `source_url`**: Re-running the importer updates existing records, never creates duplicates
- **Never truncates**: Existing data is preserved
- **Validation before writing**: All records are validated; errors are reported before any writes

## Database Migration

Versioned migrations in `init-db/` are the authoritative schema source. See [`init-db/migrate.py`](../init-db/migrate.py) for a runner that applies all migrations in order.

| File | What it adds |
|------|-------------|
| `01-init.sql` | `catalog.courses`, `resources.summaries`, `resources.links` |
| `02-syllabi.sql` | `catalog.syllabi` table + indexes |
| `03-traceability.sql` | `fetched_at`, `catalog_year`, `source_host` columns |
| `04-req-tree.sql` | `prereq_tree`, `coreq_tree` JSONB + `requirements_parsed` |
| `05-uniqueness-and-fk.sql` | `UNIQUE(course_code, catalog_year)` + composite lookup index |

> **Important:** Docker's `init-db/` scripts only run when a database volume is first created. For existing volumes, apply migrations manually (all use `IF NOT EXISTS` so they're safe to re-run).

## Semester Code Encoding

The API uses `YYYYMM` codes mapped as follows (ported from the site's JavaScript):

| Code suffix | Semester | Year adjustment |
|-------------|----------|-----------------|
| `30` or `05` | Spring | None |
| `50`, `06`, `07`* | Summer | None |
| `10` or `12` | Fall | Year decremented |

\* After 2011, code `07` is treated as `06` (Summer).

Example: `202510` → Fall 2024 (year 2025 decremented for month 10).

## Limitations

- **Syllabus text extraction is not implemented.** Syllabi are served as PDFs. The pipeline captures the download URL and metadata; text extraction is a later phase.
- **Instructor names require an extra API call per unique instructor.** The pipeline caches these to minimize requests.
- **The `--probe-syllabi` flag** sends a HEAD request per `has_syllabus=True` record and is slow for large batches. It is best-effort — a probe failure does not invalidate the record.
- **robots.txt**: The HB 2504 site returns 404 for `/robots.txt` (no restrictions). The pipeline uses a descriptive User-Agent and rate limiting regardless.
