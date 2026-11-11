CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS resources;

CREATE TABLE IF NOT EXISTS catalog.courses (
    course_code VARCHAR PRIMARY KEY,
    course_name VARCHAR NOT NULL,
    description TEXT,
    prereq_text TEXT,
    coreq_text TEXT,
    catalog_year TEXT
);

CREATE TABLE IF NOT EXISTS resources.summaries (
    summary_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_code VARCHAR NOT NULL UNIQUE,
    content TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS resources.links (
    link_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    summary_id UUID NOT NULL REFERENCES resources.summaries(summary_id),
    url TEXT NOT NULL,
    title TEXT,
    category TEXT
);
