"""Tests for `pearscarf.storage.graph` — entity/edge construction and shaping.

Mocks at the boundary of the neo4j session via `get_session`. Focus on the
construction/shaping logic, not actual Cypher execution.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from pearscarf.storage import graph


@pytest.fixture
def neo4j_session(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch `get_session` so callers receive a fresh MagicMock session."""
    session = MagicMock()
    result = MagicMock()
    result.single.return_value = None
    result.__iter__ = lambda self: iter([])
    session.run.return_value = result

    @contextmanager
    def _fake_session():
        yield session

    monkeypatch.setattr("pearscarf.storage.graph.get_session", _fake_session)
    return session


def _result(single=None, rows=None) -> MagicMock:
    """Build a result mock with single() and iter()."""
    r = MagicMock()
    r.single.return_value = single
    r.__iter__ = lambda self: iter(rows or [])
    return r


# ---- utc_to_local_date ----


def test_utc_to_local_date_str_input() -> None:
    out = graph.utc_to_local_date("2026-03-21T15:00:00+00:00")
    assert isinstance(out, str)
    assert len(out) == 10  # YYYY-MM-DD


def test_utc_to_local_date_naive_dt_treated_as_utc() -> None:
    naive = datetime(2026, 3, 21, 15, 0, 0)
    out = graph.utc_to_local_date(naive)
    assert isinstance(out, str)


# ---- _label_to_type ----


def test_label_to_type_reverse_map_for_known_label() -> None:
    assert graph._label_to_type(["Person"]) == "person"
    assert graph._label_to_type(["Company"]) == "company"


def test_label_to_type_lower_match_fallback() -> None:
    # _LABELS keys are lowercase; if label.lower() is in _LABELS, returns it
    assert graph._label_to_type(["person"]) == "person"


def test_label_to_type_unknown_returns_empty() -> None:
    assert graph._label_to_type(["WeirdLabel"]) == ""


def test_label_to_type_empty_returns_empty() -> None:
    assert graph._label_to_type([]) == ""


# ---- get_or_create_day ----


def test_get_or_create_day_returns_id(neo4j_session: MagicMock) -> None:
    neo4j_session.run.return_value = _result(single={"did": "day-123"})
    assert graph.get_or_create_day("2026-03-21") == "day-123"


def test_get_or_create_day_returns_empty_when_no_record(neo4j_session: MagicMock) -> None:
    neo4j_session.run.return_value = _result(single=None)
    assert graph.get_or_create_day("2026-03-21") == ""


# ---- ensure_constraints ----


def test_ensure_constraints_runs_create_constraint(neo4j_session: MagicMock) -> None:
    graph.ensure_constraints()
    sql = neo4j_session.run.call_args.args[0]
    assert "CREATE CONSTRAINT" in sql
    assert "Day" in sql


# ---- find_entity ----


def test_find_entity_exact_name_match(neo4j_session: MagicMock) -> None:
    node = MagicMock()
    node.get.return_value = "Alice"
    node.__iter__ = lambda self: iter({"name": "Alice", "email": "a@b"}.items())
    # dict(node) needs to work — give it a __iter__ + __getitem__
    node = {"name": "Alice", "email": "a@b", "created_at": "x"}
    neo4j_session.run.return_value = _result(single={"n": node, "eid": "node-1"})

    result = graph.find_entity("person", "Alice")
    assert result == {
        "id": "node-1",
        "type": "person",
        "name": "Alice",
        "metadata": {"email": "a@b"},
    }


def test_find_entity_returns_none_when_no_match(neo4j_session: MagicMock) -> None:
    neo4j_session.run.return_value = _result(single=None)
    assert graph.find_entity("person", "Ghost") is None


def test_find_entity_person_falls_back_to_email_match(neo4j_session: MagicMock) -> None:
    # First name lookup misses; second by email hits.
    node = {"name": "Alice", "email": "alice@x.com", "created_at": "x"}
    neo4j_session.run.side_effect = [
        _result(single=None),
        _result(single={"n": node, "eid": "node-9"}),
    ]
    out = graph.find_entity("person", "Alice", metadata_match="alice@x.com")
    assert out is not None
    assert out["id"] == "node-9"


# ---- create_entity ----


def test_create_entity_default_label_path(neo4j_session: MagicMock) -> None:
    neo4j_session.run.return_value = _result(single={"eid": "n1"})
    eid = graph.create_entity("project", "Apollo")
    assert eid == "n1"
    sql = neo4j_session.run.call_args.args[0]
    assert "MERGE (n:Project" in sql


def test_create_entity_person_with_email_uses_email_merge_key(
    neo4j_session: MagicMock,
) -> None:
    neo4j_session.run.return_value = _result(single={"eid": "n2"})
    eid = graph.create_entity("person", "Alice", {"email": "alice@x.com"})
    assert eid == "n2"
    sql = neo4j_session.run.call_args.args[0]
    assert "email" in sql.lower()


def test_create_entity_company_with_domain_uses_domain_merge_key(
    neo4j_session: MagicMock,
) -> None:
    neo4j_session.run.return_value = _result(single={"eid": "n3"})
    eid = graph.create_entity("company", "Acme", {"domain": "acme.com"})
    assert eid == "n3"
    sql = neo4j_session.run.call_args.args[0]
    assert "domain" in sql.lower()


# ---- create_fact_edge ----


def test_create_fact_edge_passes_props_and_returns_id(neo4j_session: MagicMock) -> None:
    neo4j_session.run.return_value = _result(single={"rid": "edge-7"})
    rid = graph.create_fact_edge(
        from_node_id="a",
        to_node_id="b",
        edge_label="affiliated",
        fact_type="employee",
        fact="Alice works at Acme.",
        confidence="stated",
        source_record="email_001",
        source_type="email",
        source_at="2026-03-21T00:00:00+00:00",
        valid_until=None,
    )
    assert rid == "edge-7"
    kwargs = neo4j_session.run.call_args.kwargs
    assert kwargs["rel_type"] == "AFFILIATED"
    props = kwargs["props"]
    assert props["fact"] == "Alice works at Acme."
    assert props["fact_type"] == "employee"
    assert "op_area" not in props
    assert props["source_record_ids"] == ["email_001"]


# ---- find_exact_dup_edge ----


def test_find_exact_dup_edge_returns_id_when_present(neo4j_session: MagicMock) -> None:
    neo4j_session.run.return_value = _result(single={"rid": "edge-x"})
    eid = graph.find_exact_dup_edge("a", "AFFILIATED", "employee", "b", "rec_1", "fact text")
    assert eid == "edge-x"


def test_find_exact_dup_edge_returns_none_when_absent(neo4j_session: MagicMock) -> None:
    neo4j_session.run.return_value = _result(single=None)
    assert graph.find_exact_dup_edge("a", "AFFILIATED", "employee", "b", "r", "f") is None


# ---- append_source_record ----


def test_append_source_record_skips_when_already_present(neo4j_session: MagicMock) -> None:
    # SELECT returns existing arrays containing the source already
    neo4j_session.run.return_value = _result(single={"ids": ["email_001"], "confs": ["stated"]})
    graph.append_source_record("edge-1", "email_001")
    # Only the SELECT should have run; no UPDATE
    assert neo4j_session.run.call_count == 1


def test_append_source_record_writes_when_new(neo4j_session: MagicMock) -> None:
    # First call (SELECT) returns existing arrays; second call (UPDATE) is the write
    neo4j_session.run.side_effect = [
        _result(single={"ids": ["email_001"], "confs": ["stated"]}),
        _result(single=None),
    ]
    graph.append_source_record("edge-1", "email_002", confidence="inferred")
    assert neo4j_session.run.call_count == 2
    update_call = neo4j_session.run.call_args_list[1]
    assert update_call.kwargs["ids"] == ["email_001", "email_002"]
    assert update_call.kwargs["confs"] == ["stated", "inferred"]


# ---- mark_fact_stale ----


def test_mark_fact_stale_executes_update_with_replaced_by(neo4j_session: MagicMock) -> None:
    graph.mark_fact_stale("edge-1", "edge-2")
    kwargs = neo4j_session.run.call_args.kwargs
    assert kwargs["rid"] == "edge-1"
    assert kwargs["rby"] == "edge-2"


# ---- FACT_CATEGORIES sanity ----


def test_fact_categories_contains_expected_edge_labels() -> None:
    assert set(graph.FACT_CATEGORIES.keys()) >= {"AFFILIATED", "ASSERTED", "TRANSITIONED"}


def test_fact_categories_affiliated_has_employee_type() -> None:
    assert "employee" in graph.FACT_CATEGORIES["AFFILIATED"]


# --- resolve_entity cascade (exact -> alias -> fuzzy) ---


def _ent(eid: str = "n1", name: str = "PearScarf", entity_type: str = "project") -> dict:
    return {"id": eid, "type": entity_type, "name": name, "metadata": {}}


def test_resolve_entity_exact_single_is_definitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph, "_exact_name_matches", lambda *a, **k: [_ent(eid="EX")])
    monkeypatch.setattr(graph, "_alias_matches", lambda *a, **k: [])
    monkeypatch.setattr(graph, "search_entities", lambda *a, **k: [_ent(eid="FUZZ")])
    out = graph.resolve_entity("PearScarf")
    assert out["match"] == "definitive"
    assert out["via"] == "exact"
    assert out["best"]["id"] == "EX"


def test_resolve_entity_exact_beats_substring(monkeypatch: pytest.MonkeyPatch) -> None:
    # The bug this fixes: 'PearScarf' must resolve to the exact node, never the
    # substring hit 'pearscarf-site' — so the fuzzy tier is never reached.
    monkeypatch.setattr(
        graph, "_exact_name_matches", lambda *a, **k: [_ent(eid="EXACT", name="PearScarf")]
    )
    monkeypatch.setattr(graph, "_alias_matches", lambda *a, **k: [])
    monkeypatch.setattr(
        graph, "search_entities", lambda *a, **k: [_ent(eid="SITE", name="pearscarf-site")]
    )
    out = graph.resolve_entity("PearScarf")
    assert out["via"] == "exact"
    assert out["best"]["id"] == "EXACT"


def test_resolve_entity_exact_multiple_is_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        graph, "_exact_name_matches", lambda *a, **k: [_ent(eid="A"), _ent(eid="B")]
    )
    monkeypatch.setattr(graph, "_alias_matches", lambda *a, **k: [])
    out = graph.resolve_entity("Acme")
    assert out["match"] == "candidates"
    assert out["via"] == "exact"
    assert {c["id"] for c in out["candidates"]} == {"A", "B"}


def test_resolve_entity_alias_when_no_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph, "_exact_name_matches", lambda *a, **k: [])
    monkeypatch.setattr(graph, "_alias_matches", lambda *a, **k: [_ent(eid="AL")])
    monkeypatch.setattr(graph, "search_entities", lambda *a, **k: [_ent(eid="FUZZ")])
    out = graph.resolve_entity("psc")
    assert out["match"] == "definitive"
    assert out["via"] == "alias"
    assert out["best"]["id"] == "AL"


def test_resolve_entity_fuzzy_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph, "_exact_name_matches", lambda *a, **k: [])
    monkeypatch.setattr(graph, "_alias_matches", lambda *a, **k: [])
    monkeypatch.setattr(graph, "search_entities", lambda *a, **k: [_ent(eid="F1"), _ent(eid="F2")])
    out = graph.resolve_entity("pear")
    assert out["match"] == "candidates"
    assert out["via"] == "fuzzy"
    assert out["best"]["id"] == "F1"


def test_resolve_entity_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph, "_exact_name_matches", lambda *a, **k: [])
    monkeypatch.setattr(graph, "_alias_matches", lambda *a, **k: [])
    monkeypatch.setattr(graph, "search_entities", lambda *a, **k: [])
    out = graph.resolve_entity("nope")
    assert out["match"] == "none"
    assert out["best"] is None
    assert out["candidates"] == []


# --- get_facts_for_entity directionality ---


def test_get_facts_for_entity_direction_arrow(neo4j_session: MagicMock) -> None:
    for direction, arrow in (
        ("out", "(n)-[r]->(other)"),
        ("in", "(n)<-[r]-(other)"),
        ("both", "(n)-[r]-(other)"),
    ):
        graph.get_facts_for_entity("eid", direction=direction)
        cypher = neo4j_session.run.call_args.args[0]
        assert arrow in cypher
