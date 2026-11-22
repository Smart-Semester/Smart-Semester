# Local End-to-End Runbook — Smart Semester

A concise guide for running the full stack locally: Postgres → migrations → ingest → Catalog API.

---

## Architecture Overview & Data Flow

```
                      ┌────────────────────────────────────────┐
                      │        TXST HB 2504 Web API           │
                      │       (api.hb2504.txst.edu)            │
                      └──────────────────┬─────────────────────┘
                                         │
                                         ▼
                            ingest.syllabus.cli
                   (Fetch metadata, stream & hash PDFs,
                    extract text via pypdf, extract observations)
                                         │
                                         ├─────────────────────────┐
                                         ▼                         ▼
                              catalog.syllabi            data/syllabi/*.pdf
                         catalog.syllabus_documents     (Raw PDF storage on disk;
                        catalog.syllabus_observations    optional --no-retain-pdf)
                                         │
                                         │  (Logical reference / soft FK)
                                         ▼
                                  catalog.courses
                           (Authoritative course catalog &
                             prerequisite/corequisite trees)
                                         │
                                         ▼
                             services/catalog-service
                                (GET /health, /ready,
                                 GET /courses?codes=...)
                                         │
                                         ▼
                             services/planner-service
                              (Downstream consumer via
                                   CatalogClient)
```

---

## 1. Prerequisites

- **Docker Desktop** (or Docker Engine) installed and running
- **Python 3.11+** with `pip`
- Repo cloned:

```bash
git clone <repo-url>
cd Smart-Semester
```

Install ingest and runner dependencies (from repo root):

```bash
pip install psycopg2-binary pypdf
```

> [!NOTE]
> `psycopg2-binary` is required for database operations in `init-db/migrate.py` and `--apply` ingest mode. `pypdf` is required for syllabus PDF text extraction and observation parsing.

For running the automated test suites offline:

```bash
pip install pytest httpx
```

---

## 2. Start Postgres with Docker Compose

> [!NOTE]
> All subsequent steps that touch the database require this service to be healthy first.

```bash
docker compose up -d db
```

Wait for the health check to pass (the container runs `pg_isready -U postgres -d smart_semester` every 5 s):

```bash
docker compose ps          # STATUS should show "(healthy)"
```

**Connection details (from `docker-compose.yml`):**

| Field          | Value                  |
|----------------|------------------------|
| Host           | `localhost`            |
| Port           | `5432`                 |
| Database       | `smart_semester`       |
| User           | `postgres`             |
| Password       | `postgrespassword`     |
| Volume         | `postgres_data`        |
| Container Name | `smart_semester_db`    |

> [!TIP]
> When the volume is first created, Postgres executes all `*.sql` files in `./init-db/` automatically via Docker's `/docker-entrypoint-initdb.d`. However, for existing volumes or explicit schema updates, run `init-db/migrate.py` as shown in Step 3.

---

## 3. Apply Migrations *(requires live DB)*

Run the idempotent migration runner from the repo root:

```bash
DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \
    python init-db/migrate.py
```

Or pass the URL as a positional argument:

```bash
python init-db/migrate.py postgresql://postgres:postgrespassword@localhost:5432/smart_semester
```

The script applies every `*.sql` file in `init-db/` in filename order:
1. `01-init.sql`: Base schemas (`catalog`, `resources`) and initial tables (`catalog.courses`, `resources.summaries`, `resources.links`)
2. `02-syllabi.sql`: `catalog.syllabi` table and indexes
3. `03-traceability.sql`: Source traceability columns (`fetched_at`, `catalog_year`, `source_host`)
4. `04-req-tree.sql`: Requirement JSONB trees (`prereq_tree`, `coreq_tree`) and `requirements_parsed` flag
5. `05-uniqueness-and-fk.sql`: Composite uniqueness on `catalog.courses (course_code, catalog_year)` and logical FK documentation
6. `06-syllabus-documents-and-observations.sql`: `catalog.syllabus_documents` and `catalog.syllabus_observations` tables

All migrations use `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`, so re-running is safe and idempotent.

Expected output:
```text
Connecting to database…
  Applying 01-init.sql… OK
  Applying 02-syllabi.sql… OK
  Applying 03-traceability.sql… OK
  Applying 04-req-tree.sql… OK
  Applying 05-uniqueness-and-fk.sql… OK
  Applying 06-syllabus-documents-and-observations.sql… OK
All 6 migration(s) applied successfully.
```

---

## 4. Dry-Run Ingest *(no DB required — dry-run preview)*

Preview what the pipeline would ingest without touching the database:

```bash
# Preview metadata only (1 semester per course for quick verification)
python -m ingest.syllabus.cli --max-semesters 1

# Preview metadata AND syllabus PDF download/text extraction in memory
python -m ingest.syllabus.cli --max-semesters 1 --download-syllabi
```

No `DATABASE_URL` is needed. The pipeline fetches live data from the TXST HB 2504 API, validates it, and prints a preview of the records, extraction statuses, and extracted observations. No rows are written to the database.

Expected output ends with:
```text
Re-run with --apply to write to the database.
```

---

## 5. Apply a Limited Sample Ingest *(requires live DB)*

Ingest syllabus metadata and download/extract syllabus PDFs for a limited sample (fast, ideal for first-time verification):

```bash
DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \
    python -m ingest.syllabus.cli --max-semesters 1 --download-syllabi --catalog-year 2024-2025 --apply
```

Expected output:
```text
Successfully upserted N syllabus records.
  of which M have has_syllabus=False (section exists, no syllabus available).
Successfully upserted K syllabus documents and J structured observations.
```

> [!NOTE]
> Sections where `has_syllabus=False` are valid records representing course sections that have no syllabus on file. They are recorded in `catalog.syllabi` with `has_syllabus = FALSE` and are intentionally not downloaded.

### Storage and Retention Options

| Flag / Option | Description |
|---------------|-------------|
| `--storage-dir <DIR>` | Target folder to retain raw PDF binaries (default: `data/syllabi` or `SYLLABUS_STORAGE_DIR`). |
| `--no-retain-pdf` | Process PDFs in memory and discard binaries after extraction (`file_path = NULL` in database). |
| `--reprocess` | Force re-download and re-extraction even if the SHA-256 content hash has not changed. |
| `--max-pdf-size <BYTES>` | Enforce maximum allowed PDF size (default: 10 MB = 10,485,760 bytes). |
| `--catalog-year <YEAR>` | Tag ingested records for source traceability (e.g. `2024-2025`). |

### Manual Review Queue Workflow

Documents that cannot be cleanly parsed (image-only scanned documents requiring OCR, encrypted/password-protected PDFs, corrupt files, or oversized files) are routed to an explicit manual review queue rather than silently treated as empty text:

```bash
# 1. List documents requiring manual review
DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \
    python -m ingest.syllabus.cli --list-manual-review

# 2. Resolve a document in the manual review queue
DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \
    python -m ingest.syllabus.cli --resolve-manual-review <DOCUMENT_UUID> \
        --manual-notes "Verified via OCR" \
        --manual-text-file path/to/transcribed_text.txt
```

### Verify Ingested Data in PostgreSQL

```bash
# Verify syllabus metadata records
docker exec smart_semester_db psql -U postgres -d smart_semester -c "
    SELECT has_syllabus, COUNT(*) 
    FROM catalog.syllabi 
    GROUP BY has_syllabus;
"

# Verify downloaded document statuses
docker exec smart_semester_db psql -U postgres -d smart_semester -c "
    SELECT download_status, extraction_status, COUNT(*) 
    FROM catalog.syllabus_documents 
    GROUP BY download_status, extraction_status;
"

# Verify structured extracted observations
docker exec smart_semester_db psql -U postgres -d smart_semester -c "
    SELECT category, COUNT(*) 
    FROM catalog.syllabus_observations 
    GROUP BY category;
"

# Displays course code, course name and extracted text from that specific syllabus (there may be more than on per class)
#Adjust limit to see more records or remove it completly to see everything

docker exec smart_semester_db psql -U postgres -d smart_semester -c "
  SELECT course_code, course_name, extracted_text
  FROM catalog.syllabus_documents
  INNER JOIN catalog.syllabi ON syllabus_documents.syllabus_id = syllabi.syllabus_id
  LIMIT 5;
  "
# opens psql which lets you run queries
docker exec -it smart_semester_db psql -U postgres -d smart_semester


```

---

## 6. Seed Sample Course Catalog Data *(Optional / Recommended)*

> [!IMPORTANT]
> The syllabus ingest in Step 5 populates the **syllabus archive** (`catalog.syllabi`, `catalog.syllabus_documents`, `catalog.syllabus_observations`).
>
> The Catalog API (`GET /courses`), however, queries **`catalog.courses`** — the canonical course catalog containing official titles and prerequisite trees. If `catalog.courses` has no rows, `/courses?codes=CS1428` will return an empty array `[]` (unknown codes are silently omitted per contract).
>
> To test the Catalog API end-to-end with populated course data before the catalog scraper is run, insert sample course records into `catalog.courses`:

```bash
docker exec -i smart_semester_db psql -U postgres -d smart_semester << 'EOF'
INSERT INTO catalog.courses (
    course_code, course_name, description, catalog_year, requirements_parsed, prereq_tree, coreq_tree
) VALUES
    ('CS1428', 'Foundations of Computer Science I', 'Introductory computer science course.', '2024-2025', TRUE, NULL, NULL),
    ('CS2318', 'Assembly Language', 'Computer architecture and assembly language.', '2024-2025', TRUE,
     '{"kind": "course", "code": "CS1428", "min_grade": "C"}'::jsonb, NULL),
    ('CS3358', 'Data Structures and Algorithms', 'Classic data structures and algorithms.', '2024-2025', TRUE,
     '{"kind": "all_of", "children": [{"kind": "course", "code": "CS1428", "min_grade": "C"}, {"kind": "course", "code": "CS2318", "min_grade": "C"}]}'::jsonb, NULL)
ON CONFLICT (course_code) DO UPDATE SET
    course_name = EXCLUDED.course_name,
    description = EXCLUDED.description,
    prereq_tree = EXCLUDED.prereq_tree,
    coreq_tree = EXCLUDED.coreq_tree,
    requirements_parsed = EXCLUDED.requirements_parsed;
EOF
```

Verify rows exist in `catalog.courses`:

```bash
docker exec smart_semester_db psql -U postgres -d smart_semester -c "
    SELECT course_code, course_name, requirements_parsed FROM catalog.courses;
"
```

---

## 7. Start the Catalog API Service *(requires live DB)*

Install service dependencies:

```bash
cd services/catalog-service
pip install -r requirements.txt
cd ../..
```

### Option A: Run locally with Uvicorn

From the `services/catalog-service/` directory:

```bash
cd services/catalog-service
DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \
    uvicorn catalog_app.main:app --host 0.0.0.0 --port 8001 --reload
```

Or run from the repository root:

```bash
PYTHONPATH=services/catalog-service \
DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \
    uvicorn catalog_app.main:app --host 0.0.0.0 --port 8001 --reload
```

The service will log an error and exit with code 1 on startup if `DATABASE_URL` is missing or the database is unreachable.

### Option B: Run via Docker Compose

```bash
docker compose up -d catalog-service
```

---

## 8. Query the Catalog API

### Liveness probe (no DB required)

```bash
curl http://localhost:8001/health
# → {"status":"ok"}
```

### Readiness probe (checks live DB connection)

```bash
curl http://localhost:8001/ready
# → {"status":"ready"}
# → {"status":"unavailable","detail":"..."} with HTTP 503 if DB is down
```

### Fetch course catalog entries

`codes` is repeatable; 1–20 codes per request; must be uppercase with no spaces:

```bash
# Single course (CS1428 has no prerequisites)
curl "http://localhost:8001/courses?codes=CS1428"
```

Expected JSON response:
```json
[
  {
    "code": "CS1428",
    "title": "Foundations of Computer Science I",
    "prereqs": null,
    "coreqs": null,
    "requirements_parsed": true,
    "syllabus_documents": []
  }
]
```

```bash
# Multiple courses (CS3358 with structured prerequisite tree)
curl "http://localhost:8001/courses?codes=CS1428&codes=CS3358"
```

Expected JSON response:
```json
[
  {
    "code": "CS1428",
    "title": "Foundations of Computer Science I",
    "prereqs": null,
    "coreqs": null,
    "requirements_parsed": true,
    "syllabus_documents": []
  },
  {
    "code": "CS3358",
    "title": "Data Structures and Algorithms",
    "prereqs": {
      "kind": "all_of",
      "children": [
        {
          "kind": "course",
          "code": "CS1428",
          "min_grade": "C"
        },
        {
          "kind": "course",
          "code": "CS2318",
          "min_grade": "C"
        }
      ]
    },
    "coreqs": null,
    "requirements_parsed": true,
    "syllabus_documents": [
      {
        "document_id": "aaaaaaaa-0000-0000-0000-000000000001",
        "source_url": "https://hb2504.txst.edu/.../syllabus.pdf",
        "content_type": "application/pdf",
        "original_filename": "syllabus_CS3358_001.pdf",
        "content_hash": "e3b0c44298fc1c149afb",
        "file_size": 204800,
        "download_status": "DOWNLOADED",
        "extraction_status": "EXTRACTED",
        "extracted_text": "Course syllabus for CS3358...",
        "page_count": 8,
        "character_count": 4200,
        "manual_review_required": false,
        "manual_review_reason": null,
        "manual_review_notes": null,
        "downloaded_at": "2024-09-01T12:00:00Z",
        "extracted_at": "2024-09-01T12:01:00Z",
        "semester": "Fall 2024",
        "semester_code": "202410",
        "section": "001",
        "instructor_name": "Dr. Smith",
        "has_syllabus": true
      }
    ]
  }
]
```

> [!NOTE]
> Per the [Catalog API Contract](./Catalog-API-Contract.md), unknown codes are silently omitted (not a 404).

---

## 9. Run Automated Test Suites *(Offline)*

All unit test suites run completely offline without requiring network access or a live database:

```bash
# Ingest unit & integration test suite (137 tests: downloader, extractor, observations, loader)
python -m pytest ingest/syllabus/tests/ -v

# Catalog API test suite (mocked DB; covers /health, /ready, /courses validation,
# syllabus_documents field, file_path exclusion, syllabus-only courses, and DB errors)
python -m pytest services/catalog-service/tests/ -v

# Planner service test suite (eligibility router, catalog client)
python -m pytest services/planner-service/tests/ -v
```

---

## 10. Development Tips

| Goal | Command |
|------|---------|
| Always dry-run first | `python -m ingest.syllabus.cli` (no `--apply`) |
| Download & extract syllabus PDFs | Add `--download-syllabi` (requires `--apply` for DB writes) |
| Limit semesters fetched | Add `--max-semesters 1` |
| Tag ingest run for traceability | Add `--catalog-year 2024-2025` |
| Discard raw PDFs after extraction | Add `--no-retain-pdf` |
| Force re-download / re-extraction | Add `--reprocess` |
| List manual review queue | `python -m ingest.syllabus.cli --list-manual-review` |
| Resolve manual review item | `python -m ingest.syllabus.cli --resolve-manual-review <UUID> --manual-notes "..."` |
| Abort on any fetch error | Add `--fail-on-fetch-errors` |
| Discover syllabus content-type/filename | Add `--probe-syllabi` (slow; makes HEAD requests per URL) |
| Verbose debug logging | Add `--verbose` / `-v` |
| Interactive API docs (Swagger) | Open `http://localhost:8001/docs` in a browser |

---

## 11. Troubleshooting

### `pg_isready` / container not healthy
- Check Docker logs: `docker compose logs db`
- Ensure port 5432 is free: `lsof -i :5432`
- Restart cleanly: `docker compose down -v && docker compose up -d db` (destroys volume — use only when a fresh slate is desired)

### `migrate.py` fails with connection error
- Confirm DB is healthy before running: `docker compose ps`
- Verify `DATABASE_URL` uses `localhost:5432` (not `db:5432`, which is for container-to-container networking)

### `ModuleNotFoundError: No module named 'pypdf'`
- Install PDF extraction dependencies: `pip install pypdf`

### `--apply` fails with "DATABASE_URL not set"
- The environment variable must be exported or prefixed to the command: `DATABASE_URL="..." python -m ingest.syllabus.cli --apply`

### Catalog service exits immediately at startup
- `DATABASE_URL` is missing or the DB is unreachable — the service logs the reason and exits with code 1
- Verify DB status: `docker compose ps`
- Run `curl http://localhost:8001/ready` once the service is running to confirm database readiness

### `/courses` returns `422`
- Ensure at least one `codes` parameter is provided (0 codes returns 422)
- Ensure no more than 20 codes are provided in a single request (>20 codes returns 422)
- Codes must be uppercase with no spaces (e.g., `CS3358`, not `cs3358` or `CS 3358`)

### `/courses` returns an empty array `[]`
- **Check which table was populated**:
  - `ingest.syllabus.cli` populates the syllabus archive: `catalog.syllabi`, `catalog.syllabus_documents`, and `catalog.syllabus_observations`.
  - The Catalog API endpoint `/courses` queries **both** `catalog.courses` (canonical catalog) **and** `catalog.syllabi` (syllabus archive). A code found in either table will be returned.
  - If a code exists only in `catalog.syllabi`, the response uses `syllabi.course_name` as the title, sets `prereqs`/`coreqs` to `null`, and sets `requirements_parsed` to `false`.
- Check if courses exist in `catalog.courses`:
  ```bash
  docker exec smart_semester_db psql -U postgres -d smart_semester -c "SELECT COUNT(*) FROM catalog.courses;"
  ```
- Check if courses exist in `catalog.syllabi`:
  ```bash
  docker exec smart_semester_db psql -U postgres -d smart_semester -c "SELECT COUNT(*) FROM catalog.syllabi;"
  ```
- If both counts are `0`, seed sample courses as shown in [Section 6](#6-seed-sample-course-catalog-data-optional--recommended) or run the catalog course scraper / syllabus ingest pipeline.
