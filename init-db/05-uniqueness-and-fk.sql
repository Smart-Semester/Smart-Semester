-- Migration 05: Composite uniqueness key on catalog.courses + FK from syllabi
--
-- Addresses two open checklist items:
--   • "Decide uniqueness keys, indexes, update behavior, and any retention rules."
--   • "Define whether and how syllabus metadata rows relate to canonical course
--     rows.  The current syllabus table has no foreign key."
--
-- ── catalog.courses — multi-year uniqueness ────────────────────────────────────
--
-- The original PRIMARY KEY is course_code VARCHAR, which is correct for a
-- single-year catalog.  To support multiple catalog years without a redesign,
-- we enforce that (course_code, catalog_year) is unique: the same course code
-- can appear once per catalog year, and the latest row is what the API serves
-- by default.
--
-- We cannot change a PRIMARY KEY safely inside a migration without recreating
-- the table, so we add a UNIQUE constraint on (course_code, catalog_year)
-- instead.  NULL catalog_year rows (pre-migration) are excluded from the
-- constraint by Postgres's standard NULL-inequality rule (each NULL is
-- distinct), so they never conflict.
--
-- ── catalog.syllabi — soft FK to catalog.courses ──────────────────────────────
--
-- A hard (REFERENCES) foreign key would block ingesting syllabus rows for
-- courses not yet in the catalog.  The pipeline ingests syllabi and courses
-- independently, so we document the logical relationship without a hard
-- constraint.  A partial index on course_code supports JOIN queries.
--
-- Safe to run on both fresh and existing databases.

-- ── catalog.courses ───────────────────────────────────────────────────────────

-- Unique per (course_code, catalog_year).  NULL catalog_year rows are exempt.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_courses_code_year'
          AND conrelid = 'catalog.courses'::regclass
    ) THEN
        ALTER TABLE catalog.courses
            ADD CONSTRAINT uq_courses_code_year
            UNIQUE (course_code, catalog_year);
    END IF;
END;
$$;

-- Covering index: catalog service's primary query pattern is
--   WHERE course_code = ANY($1) ORDER BY catalog_year DESC
CREATE INDEX IF NOT EXISTS idx_courses_code_year
    ON catalog.courses (course_code, catalog_year DESC NULLS LAST);

-- ── catalog.syllabi ───────────────────────────────────────────────────────────

-- Partial index to support JOIN/lookup by course_code.
-- (idx_syllabi_course_code already exists from migration 02; this is a no-op
--  if the name is reused, but we use a distinct name to be explicit.)
CREATE INDEX IF NOT EXISTS idx_syllabi_course_lookup
    ON catalog.syllabi (course_code, semester_code);

-- Document the logical relationship: syllabi.course_code → courses.course_code.
-- This is a COMMENT, not a FK constraint, to avoid blocking partial ingests.
COMMENT ON COLUMN catalog.syllabi.course_code IS
    'Logical reference to catalog.courses.course_code. '
    'No hard FK so syllabus rows can be ingested before the matching '
    'catalog course row exists.';
