"""
main.py — FastAPI application entry point.

Lifespan:
  - Reads DATABASE_URL from environment.
  - Creates a psycopg2 SimpleConnectionPool on startup; logs clearly and exits
    with code 1 if DATABASE_URL is missing or the DB is unreachable.
  - Closes the pool cleanly on shutdown.

Endpoints:
  GET /health  → {"status": "ok"}  (always 200; no DB needed)
  GET /ready   → {"status": "ready"} or 503 {"status": "unavailable", "detail": "…"}
  GET /courses → see routers/courses.py
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

import psycopg2
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from catalog_app import database
from catalog_app.routers import courses

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage the connection pool across the application lifetime."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error(
            "DATABASE_URL environment variable is not set. "
            "Cannot start without a database connection."
        )
        sys.exit(1)

    try:
        database.init_pool(database_url)
    except psycopg2.OperationalError:
        logger.error(
            "Could not connect to the database at startup. "
            "Check DATABASE_URL and ensure the database is reachable."
        )
        sys.exit(1)

    yield  # application runs here

    database.close_pool()


app = FastAPI(
    title="Smart Semester — Catalog Service",
    description="Provides structured course catalog data to the planner and other services.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(courses.router)


# ── Health / readiness ────────────────────────────────────────────────────────


@app.get("/health", tags=["ops"])
def health() -> dict:
    """Liveness probe — always returns 200 if the process is up."""
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
def ready() -> JSONResponse:
    """Readiness probe — verifies a live database connection."""
    try:
        with database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return JSONResponse(content={"status": "ready"})
    except Exception as exc:
        logger.warning("Readiness check failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "detail": str(exc)},
        )
