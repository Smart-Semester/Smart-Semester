CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS resources;

CREATE TABLE catalog.courses (
    course_code VARCHAR PRIMARY KEY,
    course_name VARCHAR NOT NULL,
    description TEXT,
    prereq_text TEXT,
    coreq_text TEXT
);

CREATE TABLE resources.summaries (
    summary_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_code VARCHAR NOT NULL UNIQUE,
    content TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE resources.links (
    link_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    summary_id UUID NOT NULL REFERENCES resources.summaries(summary_id),
    url TEXT NOT NULL,
    title TEXT,
    category TEXT
);
