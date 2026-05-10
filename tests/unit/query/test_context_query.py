"""Tests for `pearscarf.query.context_query` — read-layer routing."""

from __future__ import annotations

import pytest

from pearscarf.query import context_query


def test_find_entity_delegates_to_search_entities(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_search(query, entity_type=None, limit=10):
        captured["query"] = query
        captured["entity_type"] = entity_type
        captured["limit"] = limit
        return [{"id": "n1"}]

    monkeypatch.setattr(context_query.graph, "search_entities", fake_search)
    result = context_query.find_entity("alice", entity_type="person")
    assert result == [{"id": "n1"}]
    assert captured == {"query": "alice", "entity_type": "person", "limit": 10}


def test_get_facts_filters_by_edge_label(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = [
        {"edge_label": "AFFILIATED", "fact_type": "employee"},
        {"edge_label": "ASSERTED", "fact_type": "commitment"},
    ]
    monkeypatch.setattr(
        context_query.graph,
        "get_facts_for_entity",
        lambda eid, include_stale=False: facts,
    )
    result = context_query.get_facts("n1", edge_label="AFFILIATED")
    assert len(result) == 1
    assert result[0]["edge_label"] == "AFFILIATED"


def test_get_facts_filters_by_since(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = [
        {"edge_label": "AFFILIATED", "source_at": "2026-01-01"},
        {"edge_label": "AFFILIATED", "source_at": "2026-03-01"},
    ]
    monkeypatch.setattr(
        context_query.graph,
        "get_facts_for_entity",
        lambda eid, include_stale=False: facts,
    )
    result = context_query.get_facts("n1", since="2026-02-01")
    assert len(result) == 1
    assert result[0]["source_at"] == "2026-03-01"


def test_get_connections_passes_current_only_inverse_of_include_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_traverse(eid, max_depth=3, current_only=True, edge_labels=None):
        captured["current_only"] = current_only
        return {"nodes": [], "edges": [], "source_records": []}

    monkeypatch.setattr(context_query.graph, "traverse_fact_edges", fake_traverse)
    context_query.get_connections("n1", include_stale=True)
    assert captured["current_only"] is False
    context_query.get_connections("n1", include_stale=False)
    assert captured["current_only"] is True


def test_get_communications_returns_empty_when_entity_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(context_query.graph, "get_entity", lambda eid: None)
    assert context_query.get_communications("missing") == []


def test_vector_search_delegates_with_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_query(text, n_results=5):
        captured["text"] = text
        captured["n_results"] = n_results
        return [{"id": "r1"}]

    monkeypatch.setattr(context_query.vectorstore, "query", fake_query)
    assert context_query.vector_search("hello", n_results=3) == [{"id": "r1"}]
    assert captured == {"text": "hello", "n_results": 3}
