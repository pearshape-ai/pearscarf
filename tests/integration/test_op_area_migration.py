"""Integration coverage for the 1.34.0 op_area rename migration.

Asserts that the idempotent UPDATE in `init_db` rewrites legacy records
with `metadata.op_area='intention'` to `'reality'`, leaves other rows
alone, and is safe to re-run.

Requires the isolated test stack — `scripts/test-stack.sh up` and
`pytest --integration`.
"""

from __future__ import annotations

import json

import pytest

from pearscarf.storage import db
from pearscarf.storage.db import _get_conn

pytestmark = pytest.mark.integration


def _insert_record(record_id: str, op_area: str | None) -> None:
    metadata = {"op_area": op_area} if op_area is not None else {}
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO records (id, type, source, created_at, metadata) "
            "VALUES (%s, %s, %s, now(), %s::jsonb)",
            (record_id, "record", "test", json.dumps(metadata)),
        )
        conn.commit()


def _op_area(record_id: str) -> str | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT metadata->>'op_area' AS op_area FROM records WHERE id = %s",
            (record_id,),
        ).fetchone()
        return row["op_area"] if row else None


def test_legacy_intention_record_renamed_to_reality(clean_db) -> None:
    _insert_record("test_legacy", "intention")
    db._db_initialized = False
    db.init_db()
    assert _op_area("test_legacy") == "reality"


def test_reality_record_unchanged(clean_db) -> None:
    _insert_record("test_reality", "reality")
    db._db_initialized = False
    db.init_db()
    assert _op_area("test_reality") == "reality"


def test_record_without_op_area_unchanged(clean_db) -> None:
    _insert_record("test_no_op_area", None)
    db._db_initialized = False
    db.init_db()
    assert _op_area("test_no_op_area") is None


def test_migration_is_idempotent(clean_db) -> None:
    _insert_record("test_legacy_idempotent", "intention")
    db._db_initialized = False
    db.init_db()
    db._db_initialized = False
    db.init_db()
    assert _op_area("test_legacy_idempotent") == "reality"
