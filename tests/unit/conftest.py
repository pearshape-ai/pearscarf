"""Shared mock fixtures for unit tests.

Mocks live at the system boundary — psycopg cursor, neo4j session, qdrant
client, anthropic/openai SDK clients. Storage helpers and consumers
import these via patch points on `pearscarf.storage.db._get_conn`,
`pearscarf.storage.neo4j_client.get_session`, etc.

Module-singleton resets (vocab cache, registry cache, active-table cache)
are autouse so tests don't pollute each other.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---- module-singleton resets (autouse so every test starts clean) ----


@pytest.fixture(autouse=True)
def _reset_module_singletons() -> None:
    """Drop cached module-level state between tests."""
    from pearscarf import deployment_vocab, knowledge, registry
    from pearscarf.storage import db as db_mod
    from pearscarf.storage import store as store_mod

    deployment_vocab.reset_vocab()
    registry.reset_registry()
    knowledge._onboarding_block = None
    knowledge._onboarding_source = None
    db_mod._db_initialized = True  # bypass init_db(); tests mock _get_conn
    store_mod._active_tables = None


# ---- Postgres / store mock ----


class _CursorMock(MagicMock):
    """Stand-in for the object returned by `conn.execute(...)`.

    Tests configure `.fetchone.return_value` / `.fetchall.return_value`
    per-call; rowcount defaults to 0.
    """

    rowcount = 0


@pytest.fixture
def mock_postgres_cursor() -> _CursorMock:
    """A pre-wired cursor mock with fetchone()/fetchall() returning None/[]."""
    cursor = _CursorMock()
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    cursor.rowcount = 0
    return cursor


@pytest.fixture
def mock_postgres_conn(mock_postgres_cursor: _CursorMock) -> MagicMock:
    """A pre-wired connection mock; `conn.execute()` returns the cursor."""
    conn = MagicMock()
    conn.execute.return_value = mock_postgres_cursor
    conn.commit.return_value = None
    return conn


@pytest.fixture
def patched_get_conn(monkeypatch: pytest.MonkeyPatch, mock_postgres_conn: MagicMock):
    """Patch `pearscarf.storage.db._get_conn` to yield the mock connection.

    Returns the connection mock so tests can assert on `.execute.call_args`.
    """
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_conn():
        yield mock_postgres_conn

    monkeypatch.setattr("pearscarf.storage.db._get_conn", _fake_get_conn)
    return mock_postgres_conn


# ---- Neo4j mock ----


@pytest.fixture
def mock_neo4j_result() -> MagicMock:
    """A pre-wired neo4j Result mock."""
    result = MagicMock()
    result.single.return_value = None
    result.data.return_value = []
    result.__iter__ = lambda self: iter([])
    return result


@pytest.fixture
def mock_neo4j_session(mock_neo4j_result: MagicMock) -> MagicMock:
    """A pre-wired neo4j Session mock; `session.run(...)` returns a result."""
    session = MagicMock()
    session.run.return_value = mock_neo4j_result
    return session


@pytest.fixture
def patched_neo4j_session(monkeypatch: pytest.MonkeyPatch, mock_neo4j_session: MagicMock):
    """Patch the `get_session` context manager in neo4j_client + graph module."""
    from contextlib import contextmanager

    @contextmanager
    def _fake_session():
        yield mock_neo4j_session

    monkeypatch.setattr("pearscarf.storage.neo4j_client.get_session", _fake_session)
    monkeypatch.setattr("pearscarf.storage.graph.get_session", _fake_session)
    return mock_neo4j_session


# ---- Qdrant mock ----


@pytest.fixture
def mock_qdrant_client() -> MagicMock:
    """A pre-wired Qdrant client mock."""
    client = MagicMock()
    client.get_collections.return_value = SimpleNamespace(collections=[])
    client.upsert.return_value = None
    response = MagicMock()
    response.points = []
    client.query_points.return_value = response
    return client


# ---- Anthropic mock ----


def _anthropic_text_block(text: str) -> Any:
    return SimpleNamespace(type="text", text=text)


def _anthropic_tool_block(tool_id: str, name: str, input_: dict) -> Any:
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=input_)


def _anthropic_response(
    *,
    content: list[Any] | None = None,
    stop_reason: str = "end_turn",
    input_tokens: int = 10,
    output_tokens: int = 5,
    cache_creation: int = 0,
    cache_read: int = 0,
) -> Any:
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation,
        cache_read_input_tokens=cache_read,
    )
    return SimpleNamespace(
        content=content or [_anthropic_text_block("hi")],
        stop_reason=stop_reason,
        usage=usage,
    )


@pytest.fixture
def anthropic_response_factory():
    """Factory for synthetic anthropic responses.

    Usage:
        resp = anthropic_response_factory(content=[text_block("hi")])
    """
    return SimpleNamespace(
        text_block=_anthropic_text_block,
        tool_block=_anthropic_tool_block,
        response=_anthropic_response,
    )


@pytest.fixture
def mock_anthropic_client(anthropic_response_factory) -> MagicMock:
    """A pre-wired Anthropic client mock returning a default response."""
    client = MagicMock()
    client.messages.create.return_value = anthropic_response_factory.response()
    return client


# ---- OpenAI mock ----


def _openai_response(
    *,
    text: str = "hi",
    tool_calls: list[Any] | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    cached_tokens: int = 0,
) -> Any:
    msg = SimpleNamespace(content=text, tool_calls=tool_calls or None)
    choice = SimpleNamespace(message=msg, finish_reason=finish_reason)
    prompt_details = SimpleNamespace(cached_tokens=cached_tokens)
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_tokens_details=prompt_details,
    )
    return SimpleNamespace(choices=[choice], usage=usage)


def _openai_tool_call(tool_id: str, name: str, arguments: str) -> Any:
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(id=tool_id, function=fn)


@pytest.fixture
def openai_response_factory():
    """Factory for synthetic openai responses."""
    return SimpleNamespace(
        response=_openai_response,
        tool_call=_openai_tool_call,
    )


@pytest.fixture
def mock_openai_client(openai_response_factory) -> MagicMock:
    """A pre-wired OpenAI client mock returning a default response."""
    client = MagicMock()
    client.chat.completions.create.return_value = openai_response_factory.response()
    return client
