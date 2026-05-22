"""Tests for `pearscarf.storage.store` — record CRUD, classification, MCP keys.

Mocks at the boundary of `_get_conn` returning a connection whose
`execute()` returns a cursor with `fetchone()` / `fetchall()` / `rowcount`.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from pearscarf.storage import store


@pytest.fixture
def patched_store_conn(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch `_get_conn` for the store module specifically."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    cursor.rowcount = 0
    conn.execute.return_value = cursor

    @contextmanager
    def _fake_get_conn():
        yield conn

    monkeypatch.setattr("pearscarf.storage.store._get_conn", _fake_get_conn)
    return conn


def _set_fetchone(conn: MagicMock, value):
    """Helper: queue the next fetchone() result."""
    conn.execute.return_value.fetchone.return_value = value


# ---- save_record ----


def test_save_record_no_dedup_inserts_and_returns_id(patched_store_conn: MagicMock) -> None:
    record_id = store.save_record(
        record_type="email",
        raw="raw body",
        content="formatted",
        metadata={"sender": "a@b"},
        source="gmail",
    )
    assert record_id is not None
    assert record_id.startswith("email_")
    # Insert called for records (and dual-write may follow); commit called.
    insert_calls = [
        c for c in patched_store_conn.execute.call_args_list if "INSERT INTO records" in c.args[0]
    ]
    assert len(insert_calls) == 1
    patched_store_conn.commit.assert_called()


def test_save_record_dedup_hit_returns_none(patched_store_conn: MagicMock) -> None:
    _set_fetchone(patched_store_conn, {"id": "email_existing"})
    result = store.save_record(
        record_type="email",
        raw="raw",
        dedup_key="msg-1",
    )
    assert result is None
    # Should only have run the dedup SELECT, no INSERT
    insert_calls = [c for c in patched_store_conn.execute.call_args_list if "INSERT" in c.args[0]]
    assert insert_calls == []


def test_save_record_dedup_miss_proceeds_to_insert(patched_store_conn: MagicMock) -> None:
    _set_fetchone(patched_store_conn, None)
    record_id = store.save_record(
        record_type="email",
        raw="raw",
        dedup_key="msg-2",
    )
    assert record_id is not None


# ---- get_record ----


def test_get_record_returns_dict_when_row_present(patched_store_conn: MagicMock) -> None:
    _set_fetchone(
        patched_store_conn,
        {"id": "email_001", "type": "email", "source": "gmail", "indexed": False},
    )
    result = store.get_record("email_001")
    assert result == {
        "id": "email_001",
        "type": "email",
        "source": "gmail",
        "indexed": False,
    }


def test_get_record_returns_none_when_no_row(patched_store_conn: MagicMock) -> None:
    _set_fetchone(patched_store_conn, None)
    assert store.get_record("missing") is None


# ---- classification ----


def test_set_classification_executes_update_and_commits(patched_store_conn: MagicMock) -> None:
    store.set_classification("email_001", store.RELEVANT)
    sql = patched_store_conn.execute.call_args.args[0]
    assert "UPDATE records SET classification" in sql
    assert patched_store_conn.execute.call_args.args[1] == (store.RELEVANT, "email_001")
    patched_store_conn.commit.assert_called_once()


def test_mark_relevant_uses_relevant_label(patched_store_conn: MagicMock) -> None:
    store.mark_relevant("email_001")
    args = patched_store_conn.execute.call_args.args[1]
    assert args[0] == store.RELEVANT


# ---- MCP keys ----


def test_create_mcp_key_returns_id_name_and_raw_key(patched_store_conn: MagicMock) -> None:
    _set_fetchone(patched_store_conn, {"c": 0})
    result = store.create_mcp_key("ci-key")
    assert result["name"] == "ci-key"
    assert result["id"] == "mck_001"
    assert result["raw_key"].startswith("psk_")
    # Inserted with hash, not raw key
    insert_call = [
        c for c in patched_store_conn.execute.call_args_list if "INSERT INTO mcp_keys" in c.args[0]
    ][0]
    assert insert_call.args[1][0] == "mck_001"
    assert insert_call.args[1][1] == "ci-key"
    assert insert_call.args[1][2] != result["raw_key"]  # hashed


def test_validate_mcp_key_returns_false_when_unknown(patched_store_conn: MagicMock) -> None:
    _set_fetchone(patched_store_conn, None)
    assert store.validate_mcp_key("psk_garbage") is False


def test_validate_mcp_key_returns_true_and_updates_last_used(
    patched_store_conn: MagicMock,
) -> None:
    # Since 1.40.0 the verifier pulls all non-revoked rows and compares
    # hashes in constant time, so the mock needs to feed `fetchall` (not
    # `fetchone`) a row whose `key_hash` matches `sha256(raw_key)`.
    import hashlib

    raw = "psk_anything"
    matching_hash = hashlib.sha256(raw.encode()).hexdigest()
    patched_store_conn.execute.return_value.fetchall.return_value = [
        {"id": "mck_001", "name": "test", "key_hash": matching_hash}
    ]
    assert store.validate_mcp_key(raw) is True
    update_calls = [
        c for c in patched_store_conn.execute.call_args_list if "last_used_at" in c.args[0]
    ]
    assert len(update_calls) == 1


def test_revoke_mcp_key_returns_true_when_row_updated(patched_store_conn: MagicMock) -> None:
    patched_store_conn.execute.return_value.rowcount = 1
    assert store.revoke_mcp_key("mck_001") is True


def test_revoke_mcp_key_returns_false_when_no_row(patched_store_conn: MagicMock) -> None:
    patched_store_conn.execute.return_value.rowcount = 0
    assert store.revoke_mcp_key("mck_999") is False


# ---- expert registration ----


def test_get_enabled_expert_returns_dict_when_present(patched_store_conn: MagicMock) -> None:
    _set_fetchone(patched_store_conn, {"name": "linearscarf", "enabled": True})
    result = store.get_enabled_expert("linearscarf")
    assert result == {"name": "linearscarf", "enabled": True}


def test_get_enabled_expert_returns_none_when_missing(patched_store_conn: MagicMock) -> None:
    _set_fetchone(patched_store_conn, None)
    assert store.get_enabled_expert("missing") is None


def test_disable_enabled_expert_returns_true_when_updated(patched_store_conn: MagicMock) -> None:
    patched_store_conn.execute.return_value.rowcount = 1
    assert store.disable_enabled_expert("x") is True


def test_disable_enabled_expert_returns_false_when_no_row(patched_store_conn: MagicMock) -> None:
    patched_store_conn.execute.return_value.rowcount = 0
    assert store.disable_enabled_expert("x") is False


# ---- typed-table active table cache ----


def test_get_active_table_loads_then_caches(patched_store_conn: MagicMock) -> None:
    store._active_tables = None
    cursor = patched_store_conn.execute.return_value
    cursor.fetchall.side_effect = [
        [{"expert_name": "gm", "record_type": "email", "table_name": "gm_email_0_1_5"}],
        [{"column_name": "sender"}, {"column_name": "subject"}],
    ]
    result = store.get_active_table("email")
    assert result == ("gm_email_0_1_5", ["sender", "subject"])

    # Second call: cache hit, no further query
    pre = patched_store_conn.execute.call_count
    again = store.get_active_table("email")
    assert again == ("gm_email_0_1_5", ["sender", "subject"])
    assert patched_store_conn.execute.call_count == pre


def test_reset_active_table_cache_drops_cache() -> None:
    store._active_tables = {"x": ("t", [])}
    store.reset_active_table_cache()
    assert store._active_tables is None
