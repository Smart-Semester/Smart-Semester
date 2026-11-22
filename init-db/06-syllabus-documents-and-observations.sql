-- Migration 06: Syllabus document downloads, text extraction, and extracted observations
--
-- Supports Section 6 of the Pre-Ingestion Checklist:
--   • Retains extracted text and document metadata in the database.
--   • PDF binary files are stored on disk (file_path) with content-hash deduplication.
--   • Tracks download integrity, status (MISSING, EXCEEDS_SIZE_LIMIT, UNSUPPORTED_TYPE, etc.),
--     content hash (SHA-256), and size limits.
--   • Provides an explicit manual-review queue for unextractable or scanned documents.
--   • Stores extracted observations separately from official catalog fields, preserving
--     source-document provenance (snippets, source_url, content_hash) for downstream
--     summary generation.
--
-- Safe to re-run on fresh and existing databases (uses IF NOT EXISTS).

-- ── catalog.syllabus_documents ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS catalog.syllabus_documents (
    document_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    syllabus_id             UUID NOT NULL REFERENCES catalog.syllabi(syllabus_id) ON DELETE CASCADE,
    source_url              TEXT NOT NULL,
    file_path               TEXT,
    content_type            VARCHAR(100),
    original_filename       VARCHAR(255),
    content_hash            VARCHAR(64),
    file_size               BIGINT,
    download_status         VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    extraction_status       VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    extracted_text          TEXT,
    page_count              INTEGER,
    character_count         INTEGER,
    error_message           TEXT,
    manual_review_required  BOOLEAN NOT NULL DEFAULT FALSE,
    manual_review_reason    TEXT,
    manual_review_notes     TEXT,
    downloaded_at           TIMESTAMP WITH TIME ZONE,
    extracted_at            TIMESTAMP WITH TIME ZONE,
    created_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_syllabus_documents_syllabus_id UNIQUE (syllabus_id)
);

CREATE INDEX IF NOT EXISTS idx_syllabus_docs_syllabus_id
    ON catalog.syllabus_documents (syllabus_id);

CREATE INDEX IF NOT EXISTS idx_syllabus_docs_content_hash
    ON catalog.syllabus_documents (content_hash);

CREATE INDEX IF NOT EXISTS idx_syllabus_docs_source_url
    ON catalog.syllabus_documents (source_url);

CREATE INDEX IF NOT EXISTS idx_syllabus_docs_review
    ON catalog.syllabus_documents (manual_review_required)
    WHERE manual_review_required IS TRUE;

-- ── catalog.syllabus_observations ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS catalog.syllabus_observations (
    observation_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id      UUID NOT NULL REFERENCES catalog.syllabus_documents(document_id) ON DELETE CASCADE,
    syllabus_id      UUID NOT NULL REFERENCES catalog.syllabi(syllabus_id) ON DELETE CASCADE,
    course_code      VARCHAR NOT NULL,
    semester_code    VARCHAR NOT NULL,
    category         VARCHAR(100) NOT NULL,
    observation_key  VARCHAR(100) NOT NULL,
    observation_value TEXT NOT NULL,
    context_snippet  TEXT,
    confidence       NUMERIC(3, 2) DEFAULT 1.00,
    provenance       JSONB,
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_observations_course_code
    ON catalog.syllabus_observations (course_code);

CREATE INDEX IF NOT EXISTS idx_observations_syllabus_id
    ON catalog.syllabus_observations (syllabus_id);

CREATE INDEX IF NOT EXISTS idx_observations_document_id
    ON catalog.syllabus_observations (document_id);

CREATE INDEX IF NOT EXISTS idx_observations_category
    ON catalog.syllabus_observations (category);

CREATE INDEX IF NOT EXISTS idx_observations_provenance
    ON catalog.syllabus_observations USING gin (provenance);

COMMENT ON TABLE catalog.syllabus_observations IS
    'Extracted observations (grading, topics, textbooks, policies) kept strictly '
    'separate from official catalog.courses records. Preserves source-document '
    'provenance (snippet, URL, hash) for downstream summary generation.';
