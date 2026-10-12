# Syllabus Ingest Pipeline

Ingests CS course syllabi from the [TXST HB 2504 site](https://hb2504.txst.edu/browsecourses.html#CS) into the Smart Semester database.

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

Each class section with a syllabus produces one `SyllabusRecord` with:
- Course code and name
- Section number
- Semester (human-readable + raw code)
- Instructor name (if resolvable)
- Canonical syllabus download URL (used as the uniqueness key)
- Whether a syllabus document exists (`has_syllabus` flag)

### Pipeline Steps

| Step | Module | Description |
|------|--------|-------------|
| 1. Fetch | `fetcher.py` | Talks to the HB 2504 API with rate limiting (0.25s between requests) |
| 2. Parse | `parser.py` | Converts raw API JSON into `SyllabusRecord` dataclasses |
| 3. Validate | `validator.py` | Checks required fields, detects duplicates |
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
```

### Apply to Database

```bash
# 1. Make sure Postgres is running
docker compose up -d db

# 2. Run the migration (only needed once, or on existing databases)
#    Note: If this is a FRESH database volume, the init-db/ scripts
#    run automatically. For EXISTING volumes, run manually:
docker exec -i smart_semester_db psql -U postgres -d smart_semester < init-db/02-syllabi.sql

# 3. Run the importer with --apply
DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \
    python -m ingest.syllabus.cli --apply
```

## Database Migration

The migration script [`init-db/02-syllabi.sql`](../init-db/02-syllabi.sql) adds a `catalog.syllabi` table:

```sql
CREATE TABLE IF NOT EXISTS catalog.syllabi (
    syllabus_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_code       VARCHAR NOT NULL,
    course_name       VARCHAR NOT NULL,
    section           VARCHAR NOT NULL,
    semester          VARCHAR NOT NULL,       -- "Fall 2024"
    semester_code     VARCHAR NOT NULL,       -- "202510"
    instructor_name   VARCHAR,
    instructor_plid   VARCHAR,
    source_url        VARCHAR NOT NULL UNIQUE, -- uniqueness key
    has_syllabus      BOOLEAN NOT NULL DEFAULT FALSE,
    original_format   VARCHAR,
    syllabus_filename VARCHAR,
    credit_hours      INTEGER,
    index_num         BIGINT NOT NULL,
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

> **Important:** Docker's `init-db/` scripts only run when a database volume is first created. If you already have a `postgres_data` volume, you must run the migration manually (see step 2 above). The migration uses `IF NOT EXISTS` so it's safe to re-run.

## Safety Guarantees

- **Default is dry-run**: No `--apply` flag = no database writes
- **`DATABASE_URL` required**: Never hardcoded; must be set as an environment variable
- **Transactional writes**: The entire batch is written in a single transaction
- **Upsert on `source_url`**: Re-running the importer updates existing records, never creates duplicates
- **Never truncates**: Existing data is preserved
- **Validation before writing**: All records are validated; errors are reported before any writes

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

- **Syllabus text extraction is not implemented.** Syllabi are served as PDFs. Extracting text from PDFs would require a heavy dependency (e.g., `pdfminer`, `pymupdf`). The pipeline captures the download URL and metadata; text extraction can be added later.
- **Instructor names require an extra API call per unique instructor.** The pipeline caches these to minimize requests, but a full run across all semesters will make many API calls.
- **The `--probe-syllabi` flag** sends a HEAD request per syllabus to discover `Content-Type` and filename, but is slow for large batches (disabled by default).
- **robots.txt**: The HB 2504 site returns 404 for `/robots.txt` (no restrictions). The pipeline uses a descriptive User-Agent and rate limiting regardless.
