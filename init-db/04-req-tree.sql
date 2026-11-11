-- Migration 04: Structured prerequisite/corequisite trees
--
-- Adds two JSONB columns to catalog.courses so the catalog parser can store
-- structured requirement trees alongside the existing raw text columns.
--
-- Design:
--   prereq_tree  / coreq_tree  — parsed RequirementNode trees as JSONB.
--                                NULL means unparsed (see requirements_parsed).
--   requirements_parsed        — mirrors the API contract flag; FALSE until a
--                                parser run sets it to TRUE.
--
-- The raw prereq_text / coreq_text columns are KEPT for reference and
-- re-parsing.  Do not drop them.
--
-- Safe to run on both fresh and existing databases:
--   ADD COLUMN … IF NOT EXISTS is idempotent; existing rows get NULL / FALSE.

-- ── catalog.courses ───────────────────────────────────────────────────────────

-- Structured prereq tree (matches RequirementNode JSON shape in schemas.py).
ALTER TABLE catalog.courses
    ADD COLUMN IF NOT EXISTS prereq_tree JSONB;

-- Structured coreq tree (same shape).
ALTER TABLE catalog.courses
    ADD COLUMN IF NOT EXISTS coreq_tree JSONB;

-- Whether the raw text has been parsed into the tree columns.
-- FALSE (default) = raw text exists but tree not yet built.
-- TRUE            = tree is authoritative; NULL tree means no requirements.
ALTER TABLE catalog.courses
    ADD COLUMN IF NOT EXISTS requirements_parsed BOOLEAN NOT NULL DEFAULT FALSE;

-- GIN indexes let the catalog service efficiently query inside the JSONB trees
-- (e.g. "find all courses whose prereq tree mentions CS1428").
CREATE INDEX IF NOT EXISTS idx_courses_prereq_tree  ON catalog.courses USING gin (prereq_tree);
CREATE INDEX IF NOT EXISTS idx_courses_coreq_tree   ON catalog.courses USING gin (coreq_tree);
