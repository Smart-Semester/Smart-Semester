# Pre-Ingestion Checklist

Use this checklist to settle the data scope, API contract, and database decisions before expanding ingestion or building the syllabus scraper. The initial decisions below reflect the team's current direction; confirm any remaining open items before implementation.

## Agreed initial scope

- [x] Ingest the **current TXST catalog year** first. Design the data model so historical catalog years can be added later without a redesign.
- [x] Start HB 2504 section/syllabus-metadata ingestion with the **two most recent semesters**.
- [x] Treat the TXST catalog as the authoritative source for official course descriptions and prerequisites/corequisites. HB 2504 supplies course-section and syllabus-availability metadata only.
- [x] Keep syllabus PDF downloading and text extraction as a later phase, separate from the initial catalog and metadata work.

## 1. Confirm sources, scope, and collection policy

- [x] Confirm the catalog-year and semester scope above.
- [x] Confirm which source owns which data: TXST catalog for official course data and requirements; HB 2504 for section/syllabus metadata.
- [ ] Decide request pacing for each host. The current HB 2504 fetcher uses a 0.25-second delay; the catalog's `robots.txt` does not specify a crawl delay. Prefer conservative pacing, honor `Retry-After`, and use backoff for transient failures.
- [ ] Confirm source terms, attribution expectations, and acceptable retention for fetched catalog data and syllabus metadata.
- [ ] Document source URLs, fetch timestamps, and catalog-year/version information so ingested data can be traced and refreshed.

## 2. Finalize the shared Catalog API contract

- [ ] Preserve the contract's `GET /courses?codes=...` behavior: repeated `codes` parameters, 1–20 codes per request, uppercase codes without spaces, and HTTP 422 for invalid count or format.
- [ ] Preserve the response rule that unknown course codes are omitted from the returned array.
- [ ] Finalize the course response fields and requirement-tree node shapes: `course`, `all_of`, `any_of`, and `manual`; use `null` for no requirements.
- [x] Decide whether empty `children` lists are invalid. **Decision: invalid — `all_of`/`any_of` must have ≥1 child; enforced by `@model_validator` in `schemas.py`.**
- [x] Decide how to distinguish “no requirements” from “requirements not yet parsed/verified.” **Decision: `requirements_parsed: bool` on `CatalogResponse` — `false` = unparsed; planner treats as unknown.**
- [ ] Publish example requests, successful responses, and errors so the planner and other consumers can implement against a stable contract.

## 3. Design the database model and migrations

- [x] Keep canonical catalog courses separate from term/section syllabus metadata and any future downloaded syllabus documents or extracted text.
- [x] Decide how prerequisite/corequisite trees are stored. **Decision: `prereq_tree` / `coreq_tree` JSONB columns on `catalog.courses` (migration 04) store the parsed `RequirementNode` JSON tree; raw `prereq_text` / `coreq_text` are kept for re-parsing. `requirements_parsed BOOLEAN` mirrors the API-contract flag.**
- [x] Define whether and how syllabus metadata rows relate to canonical course rows. **Decision: soft relationship — `catalog.syllabi.course_code` documents a logical reference to `catalog.courses.course_code` (see column COMMENT in migration 05) but no hard FK, so syllabi can be ingested before the matching catalog course row exists. A composite index `idx_syllabi_course_lookup (course_code, semester_code)` supports JOIN queries.**
- [x] Retain source, catalog year, ingestion/observation timestamps, and update provenance needed for refreshes and debugging. **Already done in migration 03: `fetched_at`, `catalog_year`, `source_host` on both tables.**
- [x] Decide uniqueness keys, indexes, update behavior, and any retention rules. **Decision: `PRIMARY KEY (course_code)` stays; `UNIQUE (course_code, catalog_year)` constraint (`uq_courses_code_year`, migration 05) supports multi-year records. `idx_courses_code_year` covering index for the catalog service query pattern. Syllabi use `UNIQUE (source_url)` with `ON CONFLICT DO UPDATE` (idempotent upsert). No automatic deletion; stale rows are overwritten on re-ingest.**
- [x] Make versioned migrations the authoritative schema-management approach; do not rely on table creation inside the loader as the only schema setup. **Done: `CREATE TABLE IF NOT EXISTS` block removed from `loader.py`; migrations 01–05 in `init-db/` are the authoritative schema. `init-db/migrate.py` runner applies them in order.**
- [x] Ensure migrations work for both new Docker database volumes and existing volumes. **All migrations use `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` / `DO $$ IF NOT EXISTS … $$` guards. Docker mounts `init-db/` at `/docker-entrypoint-initdb.d` for fresh volumes; `migrate.py` handles existing volumes.**

## 4. Close gaps in the current ingestion pipeline

- [x] Confirm the current pipeline's boundary: it fetches CS course listings, semesters, class sections, and instructor metadata, then upserts syllabus listing metadata. It does not download PDFs or extract syllabus text. **Confirmed and documented in the CLI module docstring and README. Boundary: fetch → parse → validate → upsert. PDF download/extraction deferred to section 6.**
- [x] Decide how to handle sections where HB 2504 reports no syllabus. **Decision: `has_syllabus=False` rows are valid records and are stored in the database. Validator explicitly accepts them. The absence of a syllabus is meaningful data that downstream tools can surface to users. Confirmed by `TestValidatorFormatChecks::test_has_syllabus_false_still_valid`.**
- [x] Wire or remove the currently exposed `--probe-syllabi` option; it is accepted by the CLI but is not currently used. **Wired: `--probe-syllabi` now issues a HEAD request per `has_syllabus=True` record and populates `original_format` / `syllabus_filename` via `dataclasses.replace`. Best-effort — a probe failure does not invalidate the record.**
- [x] Decide whether fetch errors should block `--apply` or permit an explicitly reported partial ingest. **Decision: partial ingest is the default (pipeline continues and writes valid records). `--fail-on-fetch-errors` flag added to opt into strict mode that aborts before any writes. Both paths log a clear summary of errors. Confirmed by `TestCLIFlags`.**
- [x] Expand validation to cover course-code format, semester codes, URLs, and relationships to canonical courses, in addition to required fields and duplicate URLs. **Done in `validator.py`: regex checks for course-code format (`[A-Z]{2,6}\d{4}`), semester-code month values (`05/06/07/10/12/30/50`), and absolute HTTPS URLs. All format errors on a record are batched and reported together. Covered by `TestValidatorFormatChecks` (16 new tests; 86 total passing).**
- [x] Preserve the existing safety behavior: dry-run by default, explicit `DATABASE_URL`, transactional writes, and idempotent upserts. **Preserved. No changes to loader transaction logic or dry-run default.**

## 5. Build the Catalog service and consumer integration

- [x] Implement `services/catalog-service`; it is currently a placeholder. **Done: Fully implemented FastAPI microservice with connection pool, lifecycle management, error handling, Dockerfile, and offline unit test suite.**
- [x] Implement database access, the agreed `GET /courses` endpoint, request validation, response validation, and OpenAPI examples. **Done in `catalog_app/routers/courses.py`: `GET /courses` validates 1–20 uppercase codes without spaces (422 otherwise); queries Postgres `catalog.courses`; returns `List[CatalogResponse]`; unknown codes omitted; includes comprehensive OpenAPI examples.**
- [x] Add database connection configuration and clear startup/readiness and error behavior. **Done: Connection pool in `catalog_app/database.py` with lifespan hooks in `catalog_app/main.py`. Startup cleanly logs and fails if `DATABASE_URL` is missing or DB unreachable. `/health` provides liveness (200), and `/ready` tests database connectivity (200 / 503).**
- [x] Align planner schemas and the Catalog client with the final contract, including bounded batch requests and clear handling of unknown courses versus Catalog outages. **Done in `planner-service/app/clients/catalog.py`: `CatalogClient` batches requests (≤20 codes per query), handles timeouts/connection failures raising `CatalogUnavailableError`, and passes missing codes through cleanly without failing the batch.**
- [x] Complete the planner eligibility flow against the Catalog API. The current eligibility router is unfinished. **Done: Rewrote `eligibility.py` router and implemented `evaluator.py`. Handles code normalization, batch fetch, prereq/coreq tree evaluation (course, all_of, any_of, manual), repeated course grade deduplication (highest grade wins), unknown courses, unparsed courses (`CANNOT_VERIFY`), and catalog outages (503). Validated by 18 unit/router tests.**
- [x] Add the Catalog service to local development/deployment configuration and document how teammates run and consume it. **Done: Added `catalog-service` to `docker-compose.yml` (depends on healthy `db`), provided `Dockerfile`, `.env.example`, and comprehensive [`services/catalog-service/README.md`](../services/catalog-service/README.md).**

## 6. Keep PDF download and text extraction as a later phase

- [ ] Before starting that phase, decide whether to retain PDFs, extracted text, or both, and define size limits, retention, and reprocessing behavior.
- [ ] Add download integrity checks, content-type and filename handling, duplicate detection, and behavior for missing or changed documents.
- [ ] Test text extraction against representative PDFs, including scanned or malformed documents.
- [ ] Provide a manual-review path for unsupported/scanned documents instead of silently treating them as empty.
- [ ] Keep extracted observations distinct from official catalog fields and retain source-document provenance for future summaries.

## 7. Verify and hand off

- [ ] Add offline fixture tests for parsing, validation, and fetch-error behavior.
- [ ] Add database integration tests for migrations, relationships, and idempotent upserts.
- [ ] Add API tests for 0, 1, 20, and 21 codes; malformed codes; unknown codes; and database/service failures.
- [ ] Document a local end-to-end runbook: start Postgres and Catalog API, apply migrations, run a dry-run, apply a limited sample, and query the API.
- [ ] Assign owners for catalog ingestion, HB 2504 metadata ingestion, API contract changes, and migration review.

## Existing implementation references

- [Catalog API contract](./Catalog-API-Contract.md)
- [Initial database schema](../init-db/01-init.sql)
- [Syllabus metadata migration](../init-db/02-syllabi.sql)
- [Syllabus ingestion README](../ingest/syllabus/README.md)
- [Syllabus ingestion CLI](../ingest/syllabus/cli.py)
- [Syllabus record parser](../ingest/syllabus/parser.py)
- [Syllabus record validator](../ingest/syllabus/validator.py)
- [Syllabus database loader](../ingest/syllabus/loader.py)
- [Planner schemas](../services/planner-service/app/schemas.py)
- [Planner eligibility router](../services/planner-service/app/routers/eligibility.py)
