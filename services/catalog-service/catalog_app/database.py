"""
database.py — psycopg2 connection pool and context manager.

Usage
-----
On application startup call `init_pool(database_url)`.
Anywhere you need a connection use the `get_conn()` context manager:

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(...)
            rows = cur.fetchall()
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)

# Module-level pool — initialised once during app lifespan.
_pool: pg_pool.SimpleConnectionPool | None = None


def init_pool(database_url: str, minconn: int = 1, maxconn: int = 5) -> None:
    """Create the connection pool.  Logs a clear error and raises on failure."""
    global _pool
    logger.info("Initialising database connection pool…")
    try:
        _pool = pg_pool.SimpleConnectionPool(
            minconn=minconn,
            maxconn=maxconn,
            dsn=database_url,
        )
        logger.info("Database connection pool ready (min=%d, max=%d).", minconn, maxconn)
    except psycopg2.OperationalError as exc:
        logger.error("Failed to connect to the database: %s", exc)
        raise


def close_pool() -> None:
    """Close all connections in the pool.  Safe to call even if pool was never opened."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("Database connection pool closed.")


@contextmanager
def get_conn() -> Generator[PgConnection, None, None]:
    """Yield a connection from the pool and return it afterwards.

    The connection is NOT auto-committed; callers that write data must commit
    explicitly.  Read-only endpoints do not need to commit.
    """
    if _pool is None:
        raise RuntimeError("Database pool is not initialised.")
    conn = _pool.getconn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
