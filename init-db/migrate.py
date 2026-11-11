#!/usr/bin/env python3
"""Apply all versioned database migrations in order.

Usage
-----
    python init-db/migrate.py                        # uses DATABASE_URL env var
    python init-db/migrate.py postgres://user:pw@host/db

The script applies every *.sql file in the same directory, in filename order
(01-init.sql, 02-syllabi.sql, …).  Each file is executed in its own
transaction; on failure the transaction is rolled back and the script exits
with a non-zero status.

Safe for both fresh volumes (all migrations run) and existing volumes
(migrations use IF NOT EXISTS / ADD COLUMN IF NOT EXISTS, so re-running is
idempotent).  The script does not maintain a migrations table — the SQL files
themselves are written to be safe to re-apply.

Dependencies: psycopg2-binary (already required by the ingest pipeline).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent


def main() -> None:
    database_url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "ERROR: Provide DATABASE_URL as an argument or environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        import psycopg2  # type: ignore[import-untyped]
    except ImportError:
        print(
            "ERROR: psycopg2 is required.  Install with: pip install psycopg2-binary",
            file=sys.stderr,
        )
        sys.exit(1)

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        print("No .sql migration files found in", MIGRATIONS_DIR)
        sys.exit(0)

    print(f"Connecting to database…")
    conn = psycopg2.connect(database_url)
    try:
        for sql_file in sql_files:
            print(f"  Applying {sql_file.name}…", end=" ", flush=True)
            sql = sql_file.read_text(encoding="utf-8")
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(sql)
                print("OK")
            except Exception as exc:
                print(f"FAILED\n  {exc}", file=sys.stderr)
                sys.exit(1)
    finally:
        conn.close()

    print(f"All {len(sql_files)} migration(s) applied successfully.")


if __name__ == "__main__":
    main()
