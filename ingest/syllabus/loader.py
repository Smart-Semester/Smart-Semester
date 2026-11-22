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
    psql "$DATABASE_URL" -f init-db/06-syllabus-documents-and-observations.sql

For Docker-managed volumes the init-db/ directory is mounted at
/docker-entrypoint-initdb.d and migrations run automatically on first start.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
from typing import Optional

from .models import (
    DownloadStatus,
    ExtractionStatus,
    ObservationRecord,
    SyllabusDocumentRecord,
    SyllabusRecord,
)

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
    return d


def load_records(
    records: list[SyllabusRecord],
    database_url: str,
) -> int:
    """Write records to Postgres in a single transaction.

    Returns the number of rows upserted.
    Raises on failure (the transaction is rolled back automatically).
    """
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


UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

UPSERT_DOCUMENT_SQL = """
INSERT INTO catalog.syllabus_documents (
    syllabus_id, source_url, file_path, content_type, original_filename,
    content_hash, file_size, download_status, extraction_status,
    extracted_text, page_count, character_count, error_message,
    manual_review_required, manual_review_reason, manual_review_notes,
    downloaded_at, extracted_at, updated_at
) VALUES (
    COALESCE(
        %(explicit_syllabus_id)s,
        (SELECT syllabus_id FROM catalog.syllabi WHERE source_url = %(source_url)s)
    ),
    %(source_url)s, %(file_path)s, %(content_type)s, %(original_filename)s,
    %(content_hash)s, %(file_size)s, %(download_status)s, %(extraction_status)s,
    %(extracted_text)s, %(page_count)s, %(character_count)s, %(error_message)s,
    %(manual_review_required)s, %(manual_review_reason)s, %(manual_review_notes)s,
    %(downloaded_at)s, %(extracted_at)s, CURRENT_TIMESTAMP
)
ON CONFLICT (syllabus_id) DO UPDATE SET
    source_url = EXCLUDED.source_url,
    file_path = COALESCE(EXCLUDED.file_path, catalog.syllabus_documents.file_path),
    content_type = EXCLUDED.content_type,
    original_filename = EXCLUDED.original_filename,
    content_hash = EXCLUDED.content_hash,
    file_size = EXCLUDED.file_size,
    download_status = EXCLUDED.download_status,
    extraction_status = EXCLUDED.extraction_status,
    extracted_text = EXCLUDED.extracted_text,
    page_count = EXCLUDED.page_count,
    character_count = EXCLUDED.character_count,
    error_message = EXCLUDED.error_message,
    manual_review_required = EXCLUDED.manual_review_required,
    manual_review_reason = EXCLUDED.manual_review_reason,
    manual_review_notes = COALESCE(EXCLUDED.manual_review_notes, catalog.syllabus_documents.manual_review_notes),
    downloaded_at = COALESCE(EXCLUDED.downloaded_at, catalog.syllabus_documents.downloaded_at),
    extracted_at = COALESCE(EXCLUDED.extracted_at, catalog.syllabus_documents.extracted_at),
    updated_at = CURRENT_TIMESTAMP
RETURNING document_id;
"""

INSERT_OBSERVATION_SQL = """
INSERT INTO catalog.syllabus_observations (
    document_id, syllabus_id, course_code, semester_code,
    category, observation_key, observation_value, context_snippet,
    confidence, provenance, created_at
) VALUES (
    %(document_id)s, %(syllabus_id)s, %(course_code)s, %(semester_code)s,
    %(category)s, %(observation_key)s, %(observation_value)s, %(context_snippet)s,
    %(confidence)s, %(provenance)s, CURRENT_TIMESTAMP
);
"""


def upsert_syllabus_document(doc: SyllabusDocumentRecord, database_url: str) -> Optional[str]:
    """Upsert a syllabus document record to catalog.syllabus_documents.

    Returns the document_id (UUID string) if successful.
    """
    try:
        import psycopg2  # type: ignore[import-untyped]
    except ImportError:
        raise RuntimeError("psycopg2 is required for database operations.")

    explicit_id = doc.syllabus_id if (doc.syllabus_id and UUID_RE.match(doc.syllabus_id)) else None

    params = {
        "explicit_syllabus_id": explicit_id,
        "source_url": doc.source_url,
        "file_path": doc.file_path,
        "content_type": doc.content_type,
        "original_filename": doc.original_filename,
        "content_hash": doc.content_hash,
        "file_size": doc.file_size,
        "download_status": doc.download_status,
        "extraction_status": doc.extraction_status,
        "extracted_text": doc.extracted_text,
        "page_count": doc.page_count,
        "character_count": doc.character_count,
        "error_message": doc.error_message,
        "manual_review_required": doc.manual_review_required,
        "manual_review_reason": doc.manual_review_reason,
        "manual_review_notes": doc.manual_review_notes,
        "downloaded_at": doc.downloaded_at,
        "extracted_at": doc.extracted_at,
    }

    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(UPSERT_DOCUMENT_SQL, params)
                row = cur.fetchone()
                return str(row[0]) if row else None
    except Exception:
        logger.exception("Failed to upsert syllabus document record for %s", doc.source_url)
        raise
    finally:
        conn.close()


def load_observations(
    observations: list[ObservationRecord],
    database_url: str,
) -> int:
    """Store extracted observations into catalog.syllabus_observations idempotently.

    Preserves source-document provenance for future summary generation.
    Clears existing observations for any referenced document_ids to prevent duplicates
    on re-runs.
    Returns the count of observations inserted.
    """
    if not observations:
        return 0

    try:
        import psycopg2  # type: ignore[import-untyped]
    except ImportError:
        raise RuntimeError("psycopg2 is required for database operations.")

    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                # Group document_ids to idempotently delete previous observations
                doc_ids_to_clean = {
                    obs.document_id
                    for obs in observations
                    if obs.document_id and UUID_RE.match(obs.document_id)
                }
                for d_id in doc_ids_to_clean:
                    cur.execute(
                        "DELETE FROM catalog.syllabus_observations WHERE document_id = %s",
                        (d_id,),
                    )

                count = 0
                for obs in observations:
                    # Resolve syllabus_id if necessary
                    syllabus_id = obs.syllabus_id
                    if not (syllabus_id and UUID_RE.match(syllabus_id)):
                        cur.execute(
                            "SELECT syllabus_id FROM catalog.syllabus_documents WHERE document_id = %(doc_id)s",
                            {"doc_id": obs.document_id},
                        )
                        r = cur.fetchone()
                        if r:
                            syllabus_id = str(r[0])

                    params = {
                        "document_id": obs.document_id,
                        "syllabus_id": syllabus_id,
                        "course_code": obs.course_code,
                        "semester_code": obs.semester_code,
                        "category": obs.category,
                        "observation_key": obs.observation_key,
                        "observation_value": obs.observation_value,
                        "context_snippet": obs.context_snippet,
                        "confidence": obs.confidence,
                        "provenance": json.dumps(obs.provenance) if obs.provenance else None,
                    }
                    cur.execute(INSERT_OBSERVATION_SQL, params)
                    count += 1
                logger.info("Inserted %d observations.", count)
                return count
    except Exception:
        logger.exception("Failed to insert observations.")
        raise
    finally:
        conn.close()


def load_documents_and_observations(
    documents_and_observations: list[tuple[SyllabusDocumentRecord, list[ObservationRecord]]],
    database_url: str,
) -> tuple[int, int]:
    """Atomically and idempotently persist documents and their extracted observations.

    Uses a single database transaction for the entire batch:
    - Upserts each document record into catalog.syllabus_documents.
    - Idempotently clears previous observations for that document_id before inserting new ones.
    - Inserts new observation records preserving source-document provenance.
    - Rolls back the entire batch if any operation fails.

    Returns (docs_upserted_count, observations_inserted_count).
    """
    if not documents_and_observations:
        return (0, 0)

    try:
        import psycopg2  # type: ignore[import-untyped]
    except ImportError:
        raise RuntimeError("psycopg2 is required for database operations.")

    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                docs_count = 0
                obs_total = 0
                for doc_record, observations in documents_and_observations:
                    explicit_id = (
                        doc_record.syllabus_id
                        if (doc_record.syllabus_id and UUID_RE.match(doc_record.syllabus_id))
                        else None
                    )
                    params = {
                        "explicit_syllabus_id": explicit_id,
                        "source_url": doc_record.source_url,
                        "file_path": doc_record.file_path,
                        "content_type": doc_record.content_type,
                        "original_filename": doc_record.original_filename,
                        "content_hash": doc_record.content_hash,
                        "file_size": doc_record.file_size,
                        "download_status": doc_record.download_status,
                        "extraction_status": doc_record.extraction_status,
                        "extracted_text": doc_record.extracted_text,
                        "page_count": doc_record.page_count,
                        "character_count": doc_record.character_count,
                        "error_message": doc_record.error_message,
                        "manual_review_required": doc_record.manual_review_required,
                        "manual_review_reason": doc_record.manual_review_reason,
                        "manual_review_notes": doc_record.manual_review_notes,
                        "downloaded_at": doc_record.downloaded_at,
                        "extracted_at": doc_record.extracted_at,
                    }
                    cur.execute(UPSERT_DOCUMENT_SQL, params)
                    row = cur.fetchone()
                    if not row:
                        continue
                    doc_id = str(row[0])
                    docs_count += 1

                    # Idempotency: clear previous observations for this document_id
                    cur.execute(
                        "DELETE FROM catalog.syllabus_observations WHERE document_id = %s",
                        (doc_id,),
                    )

                    if observations:
                        cur.execute(
                            "SELECT syllabus_id FROM catalog.syllabus_documents WHERE document_id = %s",
                            (doc_id,),
                        )
                        s_row = cur.fetchone()
                        resolved_syllabus_id = str(s_row[0]) if s_row else None

                        for obs in observations:
                            obs_params = {
                                "document_id": doc_id,
                                "syllabus_id": resolved_syllabus_id or obs.syllabus_id,
                                "course_code": obs.course_code,
                                "semester_code": obs.semester_code,
                                "category": obs.category,
                                "observation_key": obs.observation_key,
                                "observation_value": obs.observation_value,
                                "context_snippet": obs.context_snippet,
                                "confidence": obs.confidence,
                                "provenance": json.dumps(obs.provenance) if obs.provenance else None,
                            }
                            cur.execute(INSERT_OBSERVATION_SQL, obs_params)
                            obs_total += 1

                logger.info(
                    "Transactionally loaded %d documents and %d observations.",
                    docs_count,
                    obs_total,
                )
                return (docs_count, obs_total)
    except Exception:
        logger.exception(
            "Transactional load of documents and observations failed — transaction rolled back."
        )
        raise
    finally:
        conn.close()


def get_document_by_source_url(
    source_url: str,
    database_url: str,
) -> Optional[SyllabusDocumentRecord]:
    """Retrieve an existing document record for change detection."""
    try:
        import psycopg2  # type: ignore[import-untyped]
    except ImportError:
        raise RuntimeError("psycopg2 is required.")

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT document_id, syllabus_id, source_url, file_path, content_type,
                       original_filename, content_hash, file_size, download_status,
                       extraction_status, extracted_text, page_count, character_count,
                       error_message, manual_review_required, manual_review_reason,
                       manual_review_notes, downloaded_at, extracted_at
                FROM catalog.syllabus_documents
                WHERE source_url = %s
                """,
                (source_url,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return SyllabusDocumentRecord(
                document_id=str(row[0]),
                syllabus_id=str(row[1]),
                source_url=row[2],
                file_path=row[3],
                content_type=row[4],
                original_filename=row[5],
                content_hash=row[6],
                file_size=row[7],
                download_status=row[8],
                extraction_status=row[9],
                extracted_text=row[10],
                page_count=row[11],
                character_count=row[12],
                error_message=row[13],
                manual_review_required=row[14],
                manual_review_reason=row[15],
                manual_review_notes=row[16],
                downloaded_at=row[17],
                extracted_at=row[18],
            )
    finally:
        conn.close()


def get_document_by_content_hash(
    content_hash: str,
    database_url: str,
) -> Optional[SyllabusDocumentRecord]:
    """Retrieve an existing document record by SHA-256 content hash for duplicate detection."""
    try:
        import psycopg2  # type: ignore[import-untyped]
    except ImportError:
        raise RuntimeError("psycopg2 is required.")

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT document_id, syllabus_id, source_url, file_path, content_type,
                       original_filename, content_hash, file_size, download_status,
                       extraction_status, extracted_text, page_count, character_count,
                       error_message, manual_review_required, manual_review_reason,
                       manual_review_notes, downloaded_at, extracted_at
                FROM catalog.syllabus_documents
                WHERE content_hash = %s
                LIMIT 1;
                """,
                (content_hash,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return SyllabusDocumentRecord(
                document_id=str(row[0]),
                syllabus_id=str(row[1]),
                source_url=row[2],
                file_path=row[3],
                content_type=row[4],
                original_filename=row[5],
                content_hash=row[6],
                file_size=row[7],
                download_status=row[8],
                extraction_status=row[9],
                extracted_text=row[10],
                page_count=row[11],
                character_count=row[12],
                error_message=row[13],
                manual_review_required=row[14],
                manual_review_reason=row[15],
                manual_review_notes=row[16],
                downloaded_at=row[17],
                extracted_at=row[18],
            )
    finally:
        conn.close()


def list_manual_review_documents(database_url: str) -> list[dict]:
    """Query documents requiring manual review."""
    try:
        import psycopg2  # type: ignore[import-untyped]
    except ImportError:
        raise RuntimeError("psycopg2 is required.")

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    d.document_id,
                    d.syllabus_id,
                    s.course_code,
                    s.section,
                    s.semester,
                    s.semester_code,
                    s.instructor_name,
                    d.source_url,
                    d.file_path,
                    d.content_type,
                    d.download_status,
                    d.extraction_status,
                    d.manual_review_reason,
                    d.manual_review_notes,
                    d.error_message,
                    d.created_at
                FROM catalog.syllabus_documents d
                JOIN catalog.syllabi s ON s.syllabus_id = d.syllabus_id
                WHERE d.manual_review_required = TRUE
                ORDER BY d.created_at DESC;
                """
            )
            columns = [desc[0] for desc in cur.description]
            results = []
            for row in cur.fetchall():
                results.append(dict(zip(columns, row)))
            return results
    finally:
        conn.close()


def resolve_manual_review(
    document_id: str,
    notes: str,
    manual_text: Optional[str],
    database_url: str,
) -> bool:
    """Resolve a document in the manual review queue."""
    try:
        import psycopg2  # type: ignore[import-untyped]
    except ImportError:
        raise RuntimeError("psycopg2 is required.")

    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE catalog.syllabus_documents
                    SET manual_review_required = FALSE,
                        manual_review_notes = %(notes)s,
                        extracted_text = COALESCE(%(manual_text)s, extracted_text),
                        extraction_status = CASE WHEN %(manual_text)s IS NOT NULL THEN 'SUCCESS' ELSE extraction_status END,
                        character_count = CASE WHEN %(manual_text)s IS NOT NULL THEN LENGTH(%(manual_text)s) ELSE character_count END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE document_id = %(document_id)s::uuid;
                    """,
                    {
                        "document_id": document_id,
                        "notes": notes,
                        "manual_text": manual_text,
                    },
                )
                return cur.rowcount > 0
    finally:
        conn.close()
