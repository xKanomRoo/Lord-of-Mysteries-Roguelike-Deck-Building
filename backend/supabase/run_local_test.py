#!/usr/bin/env python3
"""Replay cloud-save SQL fixtures in an EMPTY local PostgreSQL database.

Never use a live Supabase/user database. Requires psql on PATH. All fixture
objects and temporary test roles are rolled back in one transaction.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default="dbname=gray_fog_test", help="Local empty test database, not a production connection")
    args = parser.parse_args()
    psql = shutil.which("psql")
    if not psql:
        parser.error("psql is not installed; no SQL fixture ran")
    root = Path(__file__).resolve().parent
    # Read-only preflight prevents accidentally using an existing application DB.
    probe = subprocess.run(
        [psql, "-X", args.dsn, "-v", "ON_ERROR_STOP=1", "-At", "-c",
         "select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace "
         "where n.nspname not like 'pg_%' and n.nspname <> 'information_schema' "
         "and c.relkind in ('r','p','v','m','S');"],
        text=True, capture_output=True, check=False,
    )
    if probe.returncode != 0 or probe.stdout.strip() != "0":
        parser.error("the connection failed or the database is not empty; fixture was not run")
    schema = (root / "schema.sql").read_text(encoding="utf-8")
    statements = schema.splitlines()
    statements = [line for line in statements if line.strip().lower() not in {"begin;", "commit;"}]
    with tempfile.TemporaryDirectory(prefix="gray-fog-sql-fixture-") as tmp:
        staged = Path(tmp) / "schema-fixture.sql"
        staged.write_text("\n".join(statements) + "\n", encoding="utf-8")
        env = os.environ.copy()
        completed = subprocess.run(
            [psql, "-X", args.dsn, "-v", "ON_ERROR_STOP=1", "-v",
             f"schema_fixture_path={staged}", "-f", str(root / "test_local.sql")],
            env=env, check=False,
        )
        return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
