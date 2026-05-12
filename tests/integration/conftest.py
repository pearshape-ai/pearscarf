"""Integration test fixtures.

These tests run against the isolated test stack — see
`scripts/test-stack.sh` and `env/.test.env.example`. Connection params
are loaded from `env/.test.env` via dotenv on session start.

Run with:
    pytest --integration

(`--integration` is defined in `tests/conftest.py`; without it, every test
marked `@pytest.mark.integration` is skipped.)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import load_dotenv


@pytest.fixture(scope="session", autouse=True)
def _load_test_env() -> None:
    """Load env/.test.env into the process before any test runs."""
    repo_root = Path(__file__).resolve().parents[2]
    env_file = repo_root / "env" / ".test.env"
    if env_file.is_file():
        load_dotenv(env_file, override=True)


@pytest.fixture
def clean_db():
    """Wipe postgres + neo4j, re-run init_db and ensure_constraints.

    Function-scoped: each test sees a freshly-initialized stack. The
    `_db_initialized` flag is reset both around the wipe and after, so
    tests that re-call `init_db` (to exercise migrations against their
    own seeded data) actually run it.
    """
    from pearscarf.storage import db, graph
    from pearscarf.storage.db import _get_conn

    with _get_conn() as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.commit()

    db._db_initialized = False
    db.init_db()
    db._db_initialized = False

    with graph.get_session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    graph.ensure_constraints()
    yield
