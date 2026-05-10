"""Tests for `pearscarf.graph_access_tools` — entity-resolution tool dispatch.

ResolveEntityTool runs identifier → exact_name → alias → fuzzy in order;
each path returns one of: definitive | candidates | none. Tests mock
the underlying `graph` calls and the per-result context bundling.
"""

from __future__ import annotations

import json

import pytest

from pearscarf.graph_access_tools import (
    CheckAliasTool,
    FindEntityTool,
    GetEntityContextTool,
    ResolveEntityTool,
    SearchEntitiesTool,
)


@pytest.fixture(autouse=True)
def _stub_brief_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make context lookups deterministic and isolate ResolveEntityTool from neo4j."""
    monkeypatch.setattr(
        "pearscarf.graph_access_tools._brief_context",
        lambda eid: {"facts": [], "connections": []},
    )


def _hit(eid: str = "n1", name: str = "Alice", entity_type: str = "person") -> dict:
    return {"id": eid, "name": name, "type": entity_type, "metadata": {}}


# ---- ResolveEntityTool — identifier path ----


def test_resolve_entity_identifier_match_returns_definitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pearscarf.graph_access_tools._identifier_hit",
        lambda et, ident: _hit(eid="ID-1", name="Alice"),
    )
    monkeypatch.setattr("pearscarf.graph_access_tools._exact_name_hits", lambda *a, **k: [])
    monkeypatch.setattr("pearscarf.graph_access_tools._alias_hits", lambda *a, **k: [])

    out = json.loads(
        ResolveEntityTool().execute(entity_type="person", name="Alice", identifier="alice@x.com")
    )
    assert out["match"] == "definitive"
    assert out["via"] == "identifier"
    assert out["entity"]["id"] == "ID-1"


# ---- ResolveEntityTool — exact name path ----


def test_resolve_entity_exact_single_hit_returns_definitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pearscarf.graph_access_tools._identifier_hit", lambda *a, **k: None)
    monkeypatch.setattr(
        "pearscarf.graph_access_tools._exact_name_hits", lambda *a, **k: [_hit(eid="EX-1")]
    )
    monkeypatch.setattr("pearscarf.graph_access_tools._alias_hits", lambda *a, **k: [])

    out = json.loads(ResolveEntityTool().execute(entity_type="person", name="Alice"))
    assert out["match"] == "definitive"
    assert out["via"] == "exact_name"
    assert out["entity"]["id"] == "EX-1"


def test_resolve_entity_exact_multiple_hits_returns_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pearscarf.graph_access_tools._identifier_hit", lambda *a, **k: None)
    monkeypatch.setattr(
        "pearscarf.graph_access_tools._exact_name_hits",
        lambda *a, **k: [_hit(eid="A"), _hit(eid="B")],
    )

    out = json.loads(ResolveEntityTool().execute(entity_type="person", name="Alice"))
    assert out["match"] == "candidates"
    assert out["via"] == "exact_name_ambiguous"
    assert {c["entity"]["id"] for c in out["candidates"]} == {"A", "B"}


# ---- ResolveEntityTool — alias path ----


def test_resolve_entity_alias_single_hit_returns_definitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pearscarf.graph_access_tools._identifier_hit", lambda *a, **k: None)
    monkeypatch.setattr("pearscarf.graph_access_tools._exact_name_hits", lambda *a, **k: [])
    monkeypatch.setattr(
        "pearscarf.graph_access_tools._alias_hits", lambda *a, **k: [_hit(eid="AL-1")]
    )

    out = json.loads(ResolveEntityTool().execute(entity_type="person", name="Al"))
    assert out["match"] == "definitive"
    assert out["via"] == "alias"


def test_resolve_entity_alias_multiple_hits_returns_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pearscarf.graph_access_tools._identifier_hit", lambda *a, **k: None)
    monkeypatch.setattr("pearscarf.graph_access_tools._exact_name_hits", lambda *a, **k: [])
    monkeypatch.setattr(
        "pearscarf.graph_access_tools._alias_hits",
        lambda *a, **k: [_hit(eid="A1"), _hit(eid="A2")],
    )

    out = json.loads(ResolveEntityTool().execute(entity_type="person", name="Al"))
    assert out["match"] == "candidates"
    assert out["via"] == "alias_ambiguous"


# ---- ResolveEntityTool — fuzzy fallback / none ----


def test_resolve_entity_fuzzy_fallback_returns_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pearscarf.graph_access_tools._identifier_hit", lambda *a, **k: None)
    monkeypatch.setattr("pearscarf.graph_access_tools._exact_name_hits", lambda *a, **k: [])
    monkeypatch.setattr("pearscarf.graph_access_tools._alias_hits", lambda *a, **k: [])
    monkeypatch.setattr(
        "pearscarf.graph_access_tools.graph.search_entities",
        lambda *a, **k: [_hit(eid="F1")],
    )

    out = json.loads(ResolveEntityTool().execute(entity_type="person", name="Aly"))
    assert out["match"] == "candidates"
    assert out["via"] == "fuzzy_name"
    assert out["candidates"][0]["entity"]["id"] == "F1"


def test_resolve_entity_no_match_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pearscarf.graph_access_tools._identifier_hit", lambda *a, **k: None)
    monkeypatch.setattr("pearscarf.graph_access_tools._exact_name_hits", lambda *a, **k: [])
    monkeypatch.setattr("pearscarf.graph_access_tools._alias_hits", lambda *a, **k: [])
    monkeypatch.setattr("pearscarf.graph_access_tools.graph.search_entities", lambda *a, **k: [])

    out = json.loads(ResolveEntityTool().execute(entity_type="person", name="Ghost"))
    assert out == {"match": "none"}


# ---- FindEntityTool ----


def test_find_entity_tool_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pearscarf.graph_access_tools.graph.find_entity",
        lambda et, name: {"id": "n1", "name": name, "type": et, "metadata": {}},
    )
    out = json.loads(FindEntityTool().execute(entity_type="person", name="Alice"))
    assert out == {"found": True, "id": "n1", "name": "Alice", "type": "person", "metadata": {}}


def test_find_entity_tool_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pearscarf.graph_access_tools.graph.find_entity", lambda et, name: None)
    out = json.loads(FindEntityTool().execute(entity_type="person", name="Ghost"))
    assert out == {"found": False}


# ---- SearchEntitiesTool ----


def test_search_entities_tool_returns_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pearscarf.graph_access_tools.graph.search_entities",
        lambda q, **k: [_hit(eid="s1", name="Alice"), _hit(eid="s2", name="Alice 2")],
    )
    out = json.loads(SearchEntitiesTool().execute(query="al"))
    assert out["found"] is True
    assert {c["id"] for c in out["candidates"]} == {"s1", "s2"}


def test_search_entities_tool_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pearscarf.graph_access_tools.graph.search_entities", lambda q, **k: [])
    out = json.loads(SearchEntitiesTool().execute(query="al"))
    assert out == {"found": False, "candidates": []}


# ---- GetEntityContextTool ----


def test_get_entity_context_tool_formats_facts_and_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pearscarf.graph_access_tools.graph.get_entity_context",
        lambda eid: {
            "entity": {"name": "Alice", "type": "person"},
            "facts": [{"edge_label": "AFFILIATED", "fact": "works at Acme"}],
            "connections": [{"name": "Acme", "type": "company"}],
        },
    )
    out = GetEntityContextTool().execute(entity_id="n1")
    assert "Alice" in out
    assert "AFFILIATED" in out
    assert "Acme" in out


# ---- CheckAliasTool ----


def test_check_alias_tool_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    session = MagicMock()
    session.run.return_value.single.return_value = {"name": "Alice", "eid": "ca-1"}

    @contextmanager
    def _fake_session():
        yield session

    monkeypatch.setattr("pearscarf.graph_access_tools.graph.get_session", _fake_session)
    out = json.loads(CheckAliasTool().execute(entity_type="person", surface_form="al"))
    assert out == {"found": True, "id": "ca-1", "name": "Alice", "type": "person"}


def test_check_alias_tool_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    session = MagicMock()
    session.run.return_value.single.return_value = None

    @contextmanager
    def _fake_session():
        yield session

    monkeypatch.setattr("pearscarf.graph_access_tools.graph.get_session", _fake_session)
    out = json.loads(CheckAliasTool().execute(entity_type="person", surface_form="al"))
    assert out == {"found": False}
