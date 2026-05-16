"""Tests for `pearscarf.mcp.mcp_server` — MCP tool handlers."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from pearscarf.mcp import mcp_server
from pearscarf.records import RecordSubmissionError
from pearscarf.storage import store


@pytest.fixture
def patched_conn(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    conn.execute.return_value = cursor

    @contextmanager
    def _fake_get_conn():
        yield conn

    monkeypatch.setattr("pearscarf.mcp.mcp_server._get_conn", _fake_get_conn)
    return conn


# ---- get_schema ----


def test_get_schema_returns_vocabulary(patched_conn: MagicMock) -> None:
    patched_conn.execute.return_value.fetchall.return_value = [
        {"type": "email"},
        {"type": "issue"},
    ]
    schema = mcp_server.get_schema()
    assert "person" in schema["entity_types"]
    assert "AFFILIATED" in schema["edge_labels"]
    assert "AFFILIATED" in schema["fact_types"]
    assert schema["source_types"] == ["email", "issue"]
    assert "op_areas" not in schema


# ---- search ----


def test_search_returns_empty_when_qdrant_empty(
    monkeypatch: pytest.MonkeyPatch, patched_conn: MagicMock
) -> None:
    monkeypatch.setattr("pearscarf.mcp.mcp_server.vectorstore.query", lambda q, n_results=10: [])
    out = mcp_server.search("hello")
    assert out == {"query": "hello", "results": [], "count": 0}


def test_search_joins_records_and_filters_by_type(
    monkeypatch: pytest.MonkeyPatch, patched_conn: MagicMock
) -> None:
    monkeypatch.setattr(
        "pearscarf.mcp.mcp_server.vectorstore.query",
        lambda q, n_results=10: [
            {"id": "r1", "content": "match", "score": 0.9},
            {"id": "r2", "content": "no", "score": 0.5},
        ],
    )
    patched_conn.execute.return_value.fetchall.return_value = [
        {
            "id": "r1",
            "type": "email",
            "source": "gm",
            "classification": "relevant",
            "created_at": None,
            "expert_name": "gm",
            "metadata": {},
        },
        {
            "id": "r2",
            "type": "issue",
            "source": "ls",
            "classification": "relevant",
            "created_at": None,
            "expert_name": "ls",
            "metadata": {},
        },
    ]
    out = mcp_server.search("hello", record_type="email")
    assert out["count"] == 1
    assert out["results"][0]["record_id"] == "r1"


# ---- query_facts ----


def test_query_facts_constructs_cypher_and_normalizes(
    monkeypatch: pytest.MonkeyPatch, patched_conn: MagicMock
) -> None:
    captured: dict = {}

    class FakeSession:
        def run(self, cypher, **params):
            captured["cypher"] = cypher
            captured["params"] = params
            result = MagicMock()
            result.data.return_value = [
                {
                    "rid": "e1",
                    "edge_label": "AFFILIATED",
                    "fact_type": "employee",
                    "fact": "works",
                    "confidence": "stated",
                    "source_record": "rec_1",
                    "source_type": "email",
                    "source_at": "2026-03-21",
                    "op_area": "reality",
                    "stale": False,
                    "valid_until": None,
                    "subject_id": "n1",
                    "subject_name": "Alice",
                    "subject_labels": ["Person"],
                    "target_id": "n2",
                    "target_name": "Acme",
                    "target_date": None,
                    "target_labels": ["Company"],
                }
            ]
            return result

    @contextmanager
    def _fake_session():
        yield FakeSession()

    monkeypatch.setattr("pearscarf.mcp.mcp_server.graph.get_session", _fake_session)

    out = mcp_server.query_facts(subject="Alice", edge_label="AFFILIATED", limit=10)
    assert out["count"] == 1
    assert captured["params"]["subject_name"] == "Alice"
    assert captured["params"]["edge_label"] == "AFFILIATED"
    assert "stale IS NULL" in captured["cypher"]
    assert out["facts"][0]["target"]["name"] == "Acme"


# ---- query_records ----


def test_query_records_filters_by_type_and_classification(
    patched_conn: MagicMock,
) -> None:
    patched_conn.execute.return_value.fetchall.return_value = [
        {
            "id": "r1",
            "type": "email",
            "source": "gm",
            "classification": "relevant",
            "created_at": datetime(2026, 3, 21, tzinfo=UTC),
            "expert_name": "gm",
            "expert_version": "0.1",
            "metadata": {},
            "snippet": "hi",
        }
    ]
    out = mcp_server.query_records(type="email", classification="relevant")
    sql = patched_conn.execute.call_args.args[0]
    params = patched_conn.execute.call_args.args[1]
    assert "type = %s" in sql
    assert "classification = %s" in sql
    assert "email" in params
    assert "relevant" in params
    assert out["records"][0]["record_id"] == "r1"


def test_query_records_metadata_filter_skips_invalid_keys(
    patched_conn: MagicMock,
) -> None:
    patched_conn.execute.return_value.fetchall.return_value = []
    mcp_server.query_records(metadata={"valid_key": "v", "1bad": "x"})
    sql = patched_conn.execute.call_args.args[0]
    # Only one metadata clause should land
    assert sql.count("metadata->>") == 1


# ---- get_entity_context ----


def test_get_entity_context_invalid_format_returns_error() -> None:
    out = mcp_server.get_entity_context("Alice", format="bogus")
    assert out["error"] == "invalid_format"


def test_get_entity_context_not_found_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pearscarf.mcp.mcp_server.context_query.find_entity", lambda n, **k: [])
    out = mcp_server.get_entity_context("Ghost")
    assert out["error"] == "not_found"


# ---- submit_record ----


def test_submit_record_returns_error_when_records_not_initialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = MagicMock()
    registry.get_connect.return_value = None
    monkeypatch.setattr("pearscarf.registry.get_registry", lambda: registry)
    out = mcp_server.submit_record("body", "https://x")
    assert out["error"] == "RECORDS_NOT_INITIALIZED"


def test_submit_record_invalid_record_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = MagicMock()
    handler.ingest.side_effect = RecordSubmissionError("bad body")
    registry = MagicMock()
    registry.get_connect.return_value = handler
    monkeypatch.setattr("pearscarf.registry.get_registry", lambda: registry)
    out = mcp_server.submit_record("body", "https://x")
    assert out["error"] == "INVALID_RECORD"
    assert "bad body" in out["message"]


def test_submit_record_returns_queued_with_record_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = MagicMock()
    handler.ingest.return_value = "rec_123"
    registry = MagicMock()
    registry.get_connect.return_value = handler
    monkeypatch.setattr("pearscarf.registry.get_registry", lambda: registry)
    out = mcp_server.submit_record("body", "https://x", op_area="intent")
    assert out == {"record_id": "rec_123", "status": "queued"}


def test_submit_record_returns_duplicate_when_handler_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = MagicMock()
    handler.ingest.return_value = None
    registry = MagicMock()
    registry.get_connect.return_value = handler
    monkeypatch.setattr("pearscarf.registry.get_registry", lambda: registry)
    out = mcp_server.submit_record("body", "https://x")
    assert out["status"] == "duplicate"


# ---- get_record_status ----


def test_get_record_status_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pearscarf.storage.store.get_record", lambda rid: None)
    out = mcp_server.get_record_status("rec_x")
    assert out["error"] == "not_found"


@pytest.mark.parametrize(
    "record_state,expected_stage",
    [
        ({"indexed": True, "classification": store.RELEVANT}, "indexed"),
        ({"indexed": False, "classification": store.NOISE}, "rejected"),
        ({"indexed": False, "classification": store.UNCERTAIN}, "needs_review"),
        ({"indexed": False, "classification": store.RELEVANT}, "extracting"),
        ({"indexed": False, "classification": store.TRIAGING}, "evaluating"),
        ({"indexed": False, "classification": None}, "received"),
    ],
)
def test_get_record_status_stage_mapping(
    monkeypatch: pytest.MonkeyPatch, record_state: dict, expected_stage: str
) -> None:
    record = {"id": "r1", "created_at": None, **record_state}
    monkeypatch.setattr("pearscarf.storage.store.get_record", lambda rid: record)
    out = mcp_server.get_record_status("r1")
    assert out["stage"] == expected_stage


# ---- MCPServer dual-transport ----


def test_mcp_server_dual_transport_instantiates() -> None:
    server = mcp_server.MCPServer()
    assert server._sse_thread is None
    assert server._http_thread is None


def test_mcp_server_start_launches_both_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mock init_db and mcp.run so they don't actually block
    monkeypatch.setattr("pearscarf.mcp.mcp_server.init_db", lambda: None)
    monkeypatch.setattr("pearscarf.mcp.mcp_server.mcp.run", lambda **kw: None)

    server = mcp_server.MCPServer()
    server.start()

    assert server._sse_thread is not None
    assert server._sse_thread.name == "mcp-server-sse"
    assert server._sse_thread.daemon is True

    assert server._http_thread is not None
    assert server._http_thread.name == "mcp-server-http"
    assert server._http_thread.daemon is True
