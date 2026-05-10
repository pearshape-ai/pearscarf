"""Tests for `pearscarf.graph_query_tools` — assistant-facing read tools."""

from __future__ import annotations

import pytest

from pearscarf.graph_query_tools import (
    DayLookupTool,
    FactsLookupTool,
    GraphTraverseTool,
    SearchEntitiesTool,
    VectorSearchTool,
)

# ---- SearchEntitiesTool ----


def test_search_entities_formats_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pearscarf.graph_query_tools.context_query.find_entity",
        lambda q, entity_type=None: [
            {"id": "n1", "name": "Alice", "type": "person", "metadata": {"email": "a@b"}},
            {"id": "n2", "name": "Bob", "type": "person", "metadata": {}},
        ],
    )
    out = SearchEntitiesTool().execute(query="al")
    assert "Alice" in out
    assert "id=n1" in out
    assert "email=a@b" in out
    assert "Bob" in out


def test_search_entities_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pearscarf.graph_query_tools.context_query.find_entity", lambda q, entity_type=None: []
    )
    assert SearchEntitiesTool().execute(query="x") == "No entities found."


# ---- FactsLookupTool ----


def test_facts_lookup_groups_by_label(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pearscarf.graph_query_tools.context_query.get_facts",
        lambda eid, include_stale=False: [
            {
                "edge_label": "AFFILIATED",
                "fact_type": "employee",
                "fact": "works at Acme",
                "other_name": "Acme",
                "confidence": "stated",
            },
            {
                "edge_label": "ASSERTED",
                "fact_type": "commitment",
                "fact": "will ship Q1",
                "other_name": "",
                "confidence": "stated",
                "source_at": "2026-01-15",
            },
        ],
    )
    out = FactsLookupTool().execute(entity_id="n1")
    assert "AFFILIATED:" in out
    assert "ASSERTED:" in out
    assert "works at Acme" in out
    assert "since: 2026-01-15" in out


def test_facts_lookup_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pearscarf.graph_query_tools.context_query.get_facts",
        lambda eid, include_stale=False: [],
    )
    assert FactsLookupTool().execute(entity_id="n1") == "No facts found for this entity."


def test_facts_lookup_marks_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pearscarf.graph_query_tools.context_query.get_facts",
        lambda eid, include_stale=False: [
            {
                "edge_label": "TRANSITIONED",
                "fact_type": "status_change",
                "fact": "moved",
                "other_name": "",
                "confidence": "stated",
                "stale": True,
            },
        ],
    )
    out = FactsLookupTool().execute(entity_id="n1")
    assert "[stale]" in out


# ---- GraphTraverseTool ----


def test_graph_traverse_formats_nodes_and_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pearscarf.graph_query_tools.context_query.get_connections",
        lambda eid, **k: {
            "nodes": [
                {"id": "n1", "type": "company", "name": "Acme"},
                {"id": "d1", "type": "day", "name": "2026-01-15"},
            ],
            "edges": [
                {
                    "edge_label": "AFFILIATED",
                    "fact_type": "employee",
                    "fact": "works at Acme",
                    "source_at": "2026-01-15",
                },
            ],
            "source_records": ["email_001"],
        },
    )
    out = GraphTraverseTool().execute(entity_id="n0", max_depth=2)
    assert "Acme" in out
    assert "[Day] 2026-01-15" in out
    assert "AFFILIATED" in out
    assert "email_001" in out


def test_graph_traverse_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pearscarf.graph_query_tools.context_query.get_connections",
        lambda eid, **k: {"nodes": [], "edges": [], "source_records": []},
    )
    assert GraphTraverseTool().execute(entity_id="n0") == "No connections found."


# ---- DayLookupTool ----


def test_day_lookup_formats_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pearscarf.graph_query_tools.context_query.get_facts_for_day",
        lambda d: [
            {
                "edge_label": "ASSERTED",
                "fact_type": "commitment",
                "fact": "ships X",
                "entity_name": "Alice",
                "entity_type": "person",
                "confidence": "stated",
            },
        ],
    )
    out = DayLookupTool().execute(date="2026-01-15")
    assert "Facts for 2026-01-15:" in out
    assert "Alice" in out
    assert "ships X" in out


def test_day_lookup_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pearscarf.graph_query_tools.context_query.get_facts_for_day", lambda d: [])
    assert "No facts found for 2026-01-15" in DayLookupTool().execute(date="2026-01-15")


# ---- VectorSearchTool ----


def test_vector_search_formats_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pearscarf.graph_query_tools.context_query.vector_search",
        lambda q, n_results=5: [
            {
                "id": "email_001",
                "content": "Hi Alice, quick update on the deal." + "x" * 250,
                "metadata": {"sender": "a@b", "subject": "Update"},
                "score": 0.876,
            }
        ],
    )
    out = VectorSearchTool().execute(query="deal", n_results=3)
    assert "email_001" in out
    assert "0.876" in out
    assert "Update" in out


def test_vector_search_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pearscarf.graph_query_tools.context_query.vector_search", lambda q, n_results=5: []
    )
    assert VectorSearchTool().execute(query="x") == "No results found."
