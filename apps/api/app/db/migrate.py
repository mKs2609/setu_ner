"""
Bring a database to the current schema.

    cd apps/api
    python -m app.db.migrate            # apply what is missing
    python -m app.db.migrate --status   # show what is applied

WHY NOT JUST create_tables.py
`create_all()` creates missing tables and silently ignores changes to tables
that already exist (0009 found this the hard way). So a fresh database needs
create_all *and* the SQL migrations, and an existing one needs only the
migrations it has not had yet. This runs both, in that order, and records
which migration files were applied in `schema_migrations`.

Every migration in infra/migrations is written with IF NOT EXISTS, so running
one against a database that create_all just built is a no-op -- the record is
what stops it being re-run, not correctness.

Order:
  1. CREATE EXTENSION postgis   (hosted Postgres allows this; it must precede
                                 any geometry column)
  2. create_all                 (tables the models define and the DB lacks)
  3. infra/migrations/*.sql     (in filename order, each once)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

from app.config import get_settings
from app.db.models import Base

MIGRATIONS_DIR = Path(
    os.environ.get("SETUNER_MIGRATIONS_DIR")
    or Path(__file__).resolve().parents[4] / "infra" / "migrations"
)

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename VARCHAR PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL
)
"""


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    if not directory.is_dir():
        raise FileNotFoundError(f"migrations directory not found: {directory}")
    return sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def applied(conn) -> set[str]:
    conn.execute(text(LEDGER_DDL))
    return {r[0] for r in conn.execute(text("SELECT filename FROM schema_migrations"))}


def run(database_url: str | None = None, status_only: bool = False) -> list[str]:
    engine = create_engine(database_url or get_settings().database_url, pool_pre_ping=True)
    files = migration_files()

    with engine.begin() as conn:
        done = applied(conn)
    pending = [f for f in files if f.name not in done]

    if status_only:
        for f in files:
            print(f"  {'applied' if f.name in done else 'PENDING'}  {f.name}")
        return [f.name for f in pending]

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(engine)

    for f in pending:
        sql = f.read_text(encoding="utf-8")
        # One transaction per file: a failing migration leaves no half-applied
        # schema and no ledger row, so fixing it and re-running is safe.
        with engine.begin() as conn:
            conn.exec_driver_sql(sql)
            conn.execute(
                text("INSERT INTO schema_migrations (filename, applied_at) VALUES (:f, :t)"),
                {"f": f.name, "t": datetime.now(timezone.utc)},
            )
        print(f"  applied  {f.name}")
    if not pending:
        print("  schema is current")
    return [f.name for f in pending]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply database migrations.")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    run(status_only=args.status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
