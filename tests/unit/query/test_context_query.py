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
        lambda eid, include_stale=False, direction="both": facts,
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
        lambda eid, include_stale=False, direction="both": facts,
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


# ---- recall ----


def test_recall_no_hits_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context_query.vectorstore, "search_facts", lambda q, n_results=20: [])
    assert context_query.recall("nothing") == {"facts": [], "records": [], "entities": []}


def test_recall_ranks_by_score_drops_stale_and_rolls_up_handles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # e2 is a vector hit but absent from the graph result (staled) → dropped.
    hits = [
        {"fact_id": "e1", "score": 0.9},
        {"fact_id": "e2", "score": 0.5},
        {"fact_id": "e3", "score": 0.7},
    ]
    monkeypatch.setattr(context_query.vectorstore, "search_facts", lambda q, n_results=20: hits)

    current = [
        {
            "id": "e3",
            "source_record": "r1",
            "subject": {"id": "S1", "name": "Linus", "type": "person"},
            "target": {"id": "D1", "name": "2026-05-22", "type": "day"},
        },
        {
            "id": "e1",
            "source_record": "r1",
            "subject": {"id": "S1", "name": "Linus", "type": "person"},
            "target": {"id": "T1", "name": "h2a", "type": "project"},
        },
    ]
    monkeypatch.setattr(
        context_query.graph, "get_facts_by_ids", lambda ids, include_stale=False: current
    )

    out = context_query.recall("prospects", limit=10)

    # ranked by vector score: e1 (0.9) before e3 (0.7); e2 dropped (staled)
    assert [f["id"] for f in out["facts"]] == ["e1", "e3"]
    assert out["facts"][0]["score"] == 0.9
    # source_record rolled up with hit counts
    assert out["records"] == [{"record_id": "r1", "hit_count": 2}]
    # entities rolled up; the Day node (D1) is filtered out
    assert {e["id"] for e in out["entities"]} == {"S1", "T1"}


def test_recall_threads_include_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        context_query.vectorstore,
        "search_facts",
        lambda q, n_results=20: [{"fact_id": "e1", "score": 0.9}],
    )
    captured: dict = {}

    def fake_get(ids, include_stale=False):
        captured["include_stale"] = include_stale
        return []

    monkeypatch.setattr(context_query.graph, "get_facts_by_ids", fake_get)
    context_query.recall("q", include_stale=True)
    assert captured["include_stale"] is True


def test_get_fact_history_delegates_to_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context_query.graph, "get_fact_history", lambda eid: [{"id": eid}])
    assert context_query.get_fact_history("e9") == [{"id": "e9"}]
