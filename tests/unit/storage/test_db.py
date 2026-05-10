"""Tests for `pearscarf.storage.db` — connection-pool handling and session helpers.

Mocks at the boundary of `psycopg_pool.ConnectionPool` and `_get_conn`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pearscarf.storage import db as db_mod


@pytest.fixture(autouse=True)
def _restore_pool_state() -> None:
    """Tests below intentionally manipulate _pool / _db_initialized; restore."""
    yield
    db_mod._pool = None
    db_mod._db_initialized = False


# ---- _get_pool ----


def test_get_pool_returns_cached_pool_on_second_call() -> None:
    fake_pool = MagicMock()
    db_mod._pool = fake_pool
    assert db_mod._get_pool() is fake_pool


def test_get_pool_initializes_with_expected_kwargs() -> None:
    db_mod._pool = None
    with patch("pearscarf.storage.db.ConnectionPool") as pool_cls:
        instance = MagicMock()
        pool_cls.return_value = instance

        result = db_mod._get_pool()

        pool_cls.assert_called_once()
        ctor_kwargs = pool_cls.call_args.kwargs
        assert ctor_kwargs["min_size"] == 1
        assert ctor_kwargs["max_size"] == 10
        assert ctor_kwargs["open"] is False
        instance.open.assert_called_once_with(wait=False)
        assert result is instance


def test_close_pool_resets_singleton() -> None:
    fake_pool = MagicMock()
    db_mod._pool = fake_pool
    db_mod.close_pool()
    fake_pool.close.assert_called_once()
    assert db_mod._pool is None


def test_close_pool_no_op_when_uninitialized() -> None:
    db_mod._pool = None
    db_mod.close_pool()  # should not raise
    assert db_mod._pool is None


# ---- init_db ----


def test_init_db_idempotent_on_second_call() -> None:
    db_mod._db_initialized = False
    fake_conn = MagicMock()

    from contextlib import contextmanager

    @contextmanager
    def _fake_get_conn():
        yield fake_conn

    with patch("pearscarf.storage.db._get_conn", _fake_get_conn):
        db_mod.init_db()
        first_call_count = fake_conn.execute.call_count
        db_mod.init_db()  # second call should be a no-op
        assert fake_conn.execute.call_count == first_call_count

    assert db_mod._db_initialized is True


def test_init_db_runs_schema_when_uninitialized() -> None:
    db_mod._db_initialized = False
    fake_conn = MagicMock()

    from contextlib import contextmanager

    @contextmanager
    def _fake_get_conn():
        yield fake_conn

    with patch("pearscarf.storage.db._get_conn", _fake_get_conn):
        db_mod.init_db()

    fake_conn.execute.assert_called_once_with(db_mod._SCHEMA)
    fake_conn.commit.assert_called_once()
