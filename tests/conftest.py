"""Shared pytest fixtures for the execution harness.

Three fixtures:
- clean_graph: wipes Neo4j before each test
- clean_records: wipes Postgres records tables before each test
- mock_anthropic: replaces anthropic.Anthropic with a fake client that
  returns canned responses based on the prompt being sent

All fixtures are function-scoped — every test gets a clean slate.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from dotenv import load_dotenv

load_dotenv()

from pearscarf.db import _get_conn, init_db
from pearscarf.neo4j_client import get_session


@pytest.fixture(autouse=True)
def _init_db():
    """Ensure Postgres schema exists before any test runs."""
    init_db()


@pytest.fixture
def clean_graph():
    """Wipe Neo4j before the test runs."""
    with get_session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    yield
    # No teardown — next test wipes again on entry.


@pytest.fixture
def clean_records():
    """Wipe records and dependent tables before the test runs."""
    with _get_conn() as conn:
        conn.execute(
            "TRUNCATE curator_queue, issue_changes, issues, emails, records CASCADE"
        )
        conn.commit()
    yield


def _make_fake_response(text: str) -> SimpleNamespace:
    """Build an anthropic.Message-shaped response containing one text block."""
    block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(input_tokens=0, output_tokens=0)
    return SimpleNamespace(content=[block], usage=usage, stop_reason="end_turn")


@pytest.fixture
def mock_anthropic(monkeypatch):
    """Replace anthropic.Anthropic with a fake client.

    The fake's messages.create() routes to a canned response based on the
    system prompt content. Tests configure the routing by importing
    `tests.fixtures.llm_responses` and setting entries in `RESPONSES`.
    """
    from tests.fixtures import llm_responses

    def fake_create(*, system="", messages=None, **kwargs):
        # Find the first canned response whose key appears in the system prompt.
        # Tests register entries via llm_responses.RESPONSES[key] = json_string.
        for key, payload in llm_responses.RESPONSES.items():
            if key in (system or ""):
                return _make_fake_response(payload)
        # No match — return an empty extraction so callers don't crash.
        return _make_fake_response('{"entities": [], "facts": []}')

    fake_messages = MagicMock()
    fake_messages.create = MagicMock(side_effect=fake_create)
    fake_client = MagicMock()
    fake_client.messages = fake_messages

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: fake_client)
    yield fake_client
    llm_responses.RESPONSES.clear()
