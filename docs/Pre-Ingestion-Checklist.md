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

- [ ] Keep canonical catalog courses separate from term/section syllabus metadata and any future downloaded syllabus documents or extracted text.
- [ ] Decide how prerequisite/corequisite trees are stored. The initial database schema currently has raw `prereq_text` and `coreq_text` columns but no structured tree representation.
- [ ] Define whether and how syllabus metadata rows relate to canonical course rows. The current syllabus table has no foreign key.
- [ ] Retain source, catalog year, ingestion/observation timestamps, and update provenance needed for refreshes and debugging.
- [ ] Decide uniqueness keys, indexes, update behavior, and any retention rules.
- [ ] Make versioned migrations the authoritative schema-management approach; do not rely on table creation inside the loader as the only schema setup.
- [ ] Ensure migrations work for both new Docker database volumes and existing volumes.

## 4. Close gaps in the current ingestion pipeline

- [ ] Confirm the current pipeline's boundary: it fetches CS course listings, semesters, class sections, and instructor metadata, then upserts syllabus listing metadata. It does not download PDFs or extract syllabus text.
- [ ] Decide how to handle sections where HB 2504 reports no syllabus.
- [ ] Wire or remove the currently exposed `--probe-syllabi` option; it is accepted by the CLI but is not currently used.
- [ ] Decide whether fetch errors should block `--apply` or permit an explicitly reported partial ingest. The current CLI records individual fetch errors but may still apply valid records.
- [ ] Expand validation to cover course-code format, semester codes, URLs, and relationships to canonical courses, in addition to required fields and duplicate URLs.
- [ ] Preserve the existing safety behavior: dry-run by default, explicit `DATABASE_URL`, transactional writes, and idempotent upserts.

## 5. Build the Catalog service and consumer integration

- [ ] Implement `services/catalog-service`; it is currently a placeholder.
- [ ] Implement database access, the agreed `GET /courses` endpoint, request validation, response validation, and OpenAPI examples.
- [ ] Add database connection configuration and clear startup/readiness and error behavior.
- [ ] Align planner schemas and the Catalog client with the final contract, including bounded batch requests and clear handling of unknown courses versus Catalog outages.
- [ ] Complete the planner eligibility flow against the Catalog API. The current eligibility router is unfinished.
- [ ] Add the Catalog service to local development/deployment configuration and document how teammates run and consume it.

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
