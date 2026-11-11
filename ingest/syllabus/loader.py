"""Loader — writes validated SyllabusRecords to Postgres.

Design choices:
- Requires DATABASE_URL to be passed explicitly (never reads env directly).
- Uses a single transaction for the entire batch.
- Uses INSERT ... ON CONFLICT (source_url) DO UPDATE for safe re-runs.
- Never truncates or deletes existing data.
- Reports failures clearly.

Schema management
-----------------
The catalog.syllabi table (and all other tables) are created and evolved by
the versioned SQL migrations in init-db/*.sql, which are the authoritative
schema-management approach.  This loader no longer issues CREATE TABLE — doing
so would bypass migration history and risk schema drift.

Before running --apply against a fresh Postgres volume, apply the migrations:
    psql "$DATABASE_URL" -f init-db/01-init.sql
    psql "$DATABASE_URL" -f init-db/02-syllabi.sql
    psql "$DATABASE_URL" -f init-db/03-traceability.sql
    psql "$DATABASE_URL" -f init-db/04-req-tree.sql
    psql "$DATABASE_URL" -f init-db/05-uniqueness-and-fk.sql

For Docker-managed volumes the init-db/ directory is mounted at
/docker-entrypoint-initdb.d and migrations run automatically on first start.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Optional

from .models import SyllabusRecord

logger = logging.getLogger(__name__)

UPSERT_SQL = """
INSERT INTO catalog.syllabi (
    course_code, course_name, section, semester, semester_code,
    instructor_name, instructor_plid, source_url, has_syllabus,
    original_format, syllabus_filename, credit_hours, index_num,
    fetched_at, catalog_year, source_host,
    updated_at
) VALUES (
    %(course_code)s, %(course_name)s, %(section)s, %(semester)s, %(semester_code)s,
    %(instructor_name)s, %(instructor_plid)s, %(source_url)s, %(has_syllabus)s,
    %(original_format)s, %(syllabus_filename)s, %(credit_hours)s, %(index_num)s,
    %(fetched_at)s, %(catalog_year)s, %(source_host)s,
    CURRENT_TIMESTAMP
)
ON CONFLICT (source_url) DO UPDATE SET
    course_code     = EXCLUDED.course_code,
    course_name     = EXCLUDED.course_name,
    section         = EXCLUDED.section,
    semester        = EXCLUDED.semester,
    semester_code   = EXCLUDED.semester_code,
    instructor_name = EXCLUDED.instructor_name,
    instructor_plid = EXCLUDED.instructor_plid,
    has_syllabus    = EXCLUDED.has_syllabus,
    original_format = EXCLUDED.original_format,
    syllabus_filename = EXCLUDED.syllabus_filename,
    credit_hours    = EXCLUDED.credit_hours,
    index_num       = EXCLUDED.index_num,
    fetched_at      = EXCLUDED.fetched_at,
    catalog_year    = EXCLUDED.catalog_year,
    source_host     = EXCLUDED.source_host,
    updated_at      = CURRENT_TIMESTAMP;
"""


def _record_to_params(rec: SyllabusRecord) -> dict:
    """Convert a SyllabusRecord to a dict suitable for query params."""
    d = dataclasses.asdict(rec)
    # Remove fields not in the INSERT
    return d


def load_records(
    records: list[SyllabusRecord],
    database_url: str,
) -> int:
    """Write records to Postgres in a single transaction.

    Returns the number of rows upserted.
    Raises on failure (the transaction is rolled back automatically).
    """
    # Import psycopg2 only when actually writing — keeps it optional for
    # dry-run and testing.
    try:
        import psycopg2  # type: ignore[import-untyped]
    except ImportError:
        raise RuntimeError(
            "psycopg2 is required for --apply mode.  "
            "Install it with: pip install psycopg2-binary"
        )

    logger.info("Connecting to database...")
    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                count = 0
                for rec in records:
                    cur.execute(UPSERT_SQL, _record_to_params(rec))
                    count += 1
                logger.info("Upserted %d syllabus records.", count)
        return count
    except Exception:
        logger.exception("Database write failed — transaction rolled back.")
        raise
    finally:
        conn.close()
