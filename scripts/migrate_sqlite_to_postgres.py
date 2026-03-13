#!/usr/bin/env python3
"""One-time migration: SQLite → Postgres.

Usage:
    python scripts/migrate_sqlite_to_postgres.py [sqlite_path]

Defaults to data/pearscaff.db if no path given.
Postgres connection uses POSTGRES_* env vars (loaded from .env).
"""

from __future__ import annotations

import json
import sqlite3
import sys

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from pearscaff.config import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from pearscaff.db import init_db

SQLITE_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/pearscaff.db"

# Migration order respects foreign keys
TABLES = [
    "sessions",
    "messages",
    "discord_threads",
    "entity_types",
    "records",
    "emails",
    "entities",
    "edges",
    "facts",
]

# Columns that need JSON string → Python object for JSONB
JSON_COLUMNS = {
    "messages": ["data"],
    "entities": ["metadata"],
    "entity_types": ["extract_fields"],
}

# Columns that need INTEGER 0/1 → BOOLEAN
BOOL_COLUMNS = {
    "messages": ["read"],
    "records": ["indexed"],
}


def migrate() -> None:
    print(f"Migrating from {SQLITE_PATH} to Postgres...")

    # 1. Connect to SQLite
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row

    # 2. Init Postgres schema
    init_db()

    # 3. Connect to Postgres
    conninfo = (
        f"host={POSTGRES_HOST} port={POSTGRES_PORT} "
        f"dbname={POSTGRES_DB} user={POSTGRES_USER} password={POSTGRES_PASSWORD}"
    )
    pg_conn = psycopg.connect(conninfo, row_factory=dict_row)

    for table in TABLES:
        rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            print(f"  {table}: 0 rows (skip)")
            continue

        columns = rows[0].keys()
        placeholders = ", ".join(["%s"] * len(columns))
        col_names = ", ".join(f'"{c}"' for c in columns)
        insert_sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

        json_cols = JSON_COLUMNS.get(table, [])
        bool_cols = BOOL_COLUMNS.get(table, [])

        with pg_conn.cursor() as cur:
            for row in rows:
                values = []
                for col in columns:
                    val = row[col]
                    if col in json_cols and isinstance(val, str):
                        try:
                            val = Jsonb(json.loads(val))
                        except (json.JSONDecodeError, TypeError):
                            val = Jsonb({})
                    if col in bool_cols:
                        val = bool(val)
                    values.append(val)
                cur.execute(insert_sql, values)
        pg_conn.commit()

        # Validate
        pg_count = pg_conn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()["c"]
        sqlite_count = len(rows)
        status = "OK" if pg_count >= sqlite_count else "MISMATCH"
        print(f"  {table}: {sqlite_count} SQLite → {pg_count} Postgres [{status}]")

    # Reset the messages sequence to max id
    pg_conn.execute(
        "SELECT setval('messages_id_seq', COALESCE((SELECT MAX(id) FROM messages), 0))"
    )
    pg_conn.commit()

    pg_conn.close()
    sqlite_conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    migrate()
