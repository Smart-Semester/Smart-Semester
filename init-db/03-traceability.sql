-- Migration 03: Add source-traceability columns
--
-- Adds fetched_at, catalog_year, and source_host to catalog.syllabi so that
-- every ingested row can be traced back to its upstream source, the ingestion
-- run that produced it, and the catalog year it belongs to.
--
-- Also adds fetched_at and catalog_year to catalog.courses for the same reason.
--
-- Safe to run on both fresh and existing databases:
--   • ADD COLUMN ... IF NOT EXISTS is idempotent.
--   • The DEFAULT fills existing rows so the NOT NULL constraint is satisfied.
--
-- Existing rows get sensible sentinel values:
--   fetched_at   → current_timestamp  (best approximation; row was clearly fetched)
--   catalog_year → NULL               (genuinely unknown for pre-migration rows)
--   source_host  → 'api.hb2504.txst.edu' (the only host used before this migration)

-- ── catalog.syllabi ───────────────────────────────────────────────────────────

-- When this API call was made (distinct from created_at / updated_at, which
-- record row lifecycle, not upstream-data freshness).
ALTER TABLE catalog.syllabi
    ADD COLUMN IF NOT EXISTS fetched_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- Catalog year the data belongs to, e.g. '2024-2025'.  NULL = unknown.
ALTER TABLE catalog.syllabi
    ADD COLUMN IF NOT EXISTS catalog_year VARCHAR;

-- Hostname of the upstream API or website, e.g. 'api.hb2504.txst.edu'.
ALTER TABLE catalog.syllabi
    ADD COLUMN IF NOT EXISTS source_host  VARCHAR NOT NULL DEFAULT 'api.hb2504.txst.edu';

-- ── catalog.courses ───────────────────────────────────────────────────────────

-- When this catalog page / API response was fetched.
ALTER TABLE catalog.courses
    ADD COLUMN IF NOT EXISTS fetched_at   TIMESTAMP;

-- Catalog year for this course record, e.g. '2024-2025'.
-- catalog.courses already has a catalog_year column (from 01-init.sql), so we
-- skip adding it again.  This comment is intentional documentation.

-- Hostname of the catalog source used to ingest this course.
ALTER TABLE catalog.courses
    ADD COLUMN IF NOT EXISTS source_host  VARCHAR;
