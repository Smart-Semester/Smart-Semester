-- Migration: Add catalog.syllabi table
-- Safe to run on existing databases (uses IF NOT EXISTS).
--
-- This table stores syllabus records discovered from the TXST HB 2504 site.
-- It is separate from the existing catalog.courses table — a course may have
-- many syllabi across different semesters, sections, and instructors.
--
-- Uniqueness key: source_url (the canonical syllabus download URL).

CREATE TABLE IF NOT EXISTS catalog.syllabi (
    syllabus_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_code       VARCHAR NOT NULL,
    course_name       VARCHAR NOT NULL,
    section           VARCHAR NOT NULL,
    semester          VARCHAR NOT NULL,
    semester_code     VARCHAR NOT NULL,
    instructor_name   VARCHAR,
    instructor_plid   VARCHAR,
    source_url        VARCHAR NOT NULL UNIQUE,
    has_syllabus      BOOLEAN NOT NULL DEFAULT FALSE,
    original_format   VARCHAR,
    syllabus_filename VARCHAR,
    credit_hours      INTEGER,
    index_num         BIGINT NOT NULL,
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_syllabi_course_code ON catalog.syllabi (course_code);
CREATE INDEX IF NOT EXISTS idx_syllabi_semester_code ON catalog.syllabi (semester_code);
