"""Tests for `pearscarf.curation.Curation` — supersession scan + judge."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from pearscarf.curation import Curation


def _edge(
    edge_id: str,
    source_at: str,
    fact: str = "fact text",
    fact_type: str = "decision",
    edge_label: str = "ASSERTED",
    from_id: str = "from_id_a",
    from_name: str = "PearScarf",
    to_id: str = "to_id_x",
    to_name: str = "Acme",
    to_labels: list[str] | None = None,
    recorded_at: str = "",
    created_at: str = "",
) -> dict[str, Any]:
    return {
        "edge_id": edge_id,
        "edge_label": edge_label,
        "fact_type": fact_type,
        "fact": fact,
        "source_at": source_at,
        "recorded_at": recorded_at or source_at,
        "created_at": created_at or source_at,
        "from_id": from_id,
        "from_name": from_name,
        "to_id": to_id,
        "to_name": to_name,
        "to_labels": to_labels or ["Project"],
    }


@pytest.fixture
def curation() -> Curation:
    """Build a Curation instance without running its setup loop."""
    c = Curation.__new__(Curation)
    c._last_cycle_upgrades = 0
    c._last_cycle_expired = 0
    c._last_cycle_superseded = 0
    c._last_cycle_at = None
    c._current_record_id = None
    c.total_input_tokens = 0
    c.total_output_tokens = 0
    return c


@pytest.fixture(autouse=True)
def _bypass_tracked_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock `tracked_call` to skip its DB-write side effect; preserve invoke behavior."""
    monkeypatch.setattr(
        "pearscarf.curation.tracked_call",
        lambda client, agent_name, **kwargs: client.invoke(**kwargs),
    )


def _stub_llm_response(text: str, input_tokens: int = 100, output_tokens: int = 50) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.stop_reason = "end_turn"
    resp.usage = MagicMock()
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    return resp


# ---- _format_judge_input ----


def test_format_judge_input_entity_target(curation: Curation) -> None:
    trigger = _edge("eid_new", "2026-05-10", fact="Acme renewed through 2027-Q1")
    sib = _edge("eid_old", "2026-04-01", fact="Acme renewed through 2026-Q3")
    text = curation._format_judge_input(trigger, [sib])
    assert "edge_id: eid_new" in text
    assert "edge_id: eid_old" in text
    assert "Acme renewed through 2027-Q1" in text
    assert "to: Acme" in text
    assert "TRIGGER" in text
    assert "EXISTING SIBLINGS" in text
    assert "(N=1)" in text


def test_format_judge_input_day_target_renders_as_day_node(curation: Curation) -> None:
    trigger = _edge("eid_new", "2026-05-10", to_name="2026-05-10", to_labels=["Day"])
    sib = _edge("eid_old", "2026-05-04", to_name="2026-05-04", to_labels=["Day"])
    text = curation._format_judge_input(trigger, [sib])
    assert "to: Day(2026-05-10)" in text
    assert "to: Day(2026-05-04)" in text


def test_format_judge_input_multiple_siblings_numbered(curation: Curation) -> None:
    trigger = _edge("eid_new", "2026-05-10")
    sibs = [_edge(f"eid_{i}", f"2026-04-{i:02d}") for i in (1, 2, 3)]
    text = curation._format_judge_input(trigger, sibs)
    assert "(N=3)" in text
    assert "1. edge_id: eid_1" in text
    assert "2. edge_id: eid_2" in text
    assert "3. edge_id: eid_3" in text


# ---- _judge_supersession ----


def test_judge_supersession_returns_empty_when_no_siblings(curation: Curation) -> None:
    trigger = _edge("eid_new", "2026-05-10")
    assert curation._judge_supersession(trigger, []) == []


def test_judge_supersession_parses_clean_json(
    curation: Curation, monkeypatch: pytest.MonkeyPatch
) -> None:
    trigger = _edge("eid_new", "2026-05-10")
    sib = _edge("eid_old", "2026-04-01")
    payload = (
        '{"decisions": [{"sibling_edge_id": "eid_old", '
        '"decision": "trigger_supersedes_sibling", "reason": "later"}]}'
    )

    client = MagicMock()
    client.invoke.return_value = _stub_llm_response(payload)
    monkeypatch.setattr("pearscarf.curation.get_llm_client", lambda *a, **kw: client)

    decisions = curation._judge_supersession(trigger, [sib])
    assert decisions == [
        {
            "sibling_edge_id": "eid_old",
            "decision": "trigger_supersedes_sibling",
            "reason": "later",
        }
    ]


def test_judge_supersession_accumulates_tokens(
    curation: Curation, monkeypatch: pytest.MonkeyPatch
) -> None:
    trigger = _edge("eid_new", "2026-05-10")
    sib = _edge("eid_old", "2026-04-01")

    client = MagicMock()
    client.invoke.return_value = _stub_llm_response('{"decisions": []}', 150, 75)
    monkeypatch.setattr("pearscarf.curation.get_llm_client", lambda *a, **kw: client)

    curation._judge_supersession(trigger, [sib])
    assert curation.total_input_tokens == 150
    assert curation.total_output_tokens == 75

    # Second call accumulates.
    client.invoke.return_value = _stub_llm_response('{"decisions": []}', 50, 25)
    curation._judge_supersession(trigger, [sib])
    assert curation.total_input_tokens == 200
    assert curation.total_output_tokens == 100


def test_judge_supersession_strips_markdown_fences(
    curation: Curation, monkeypatch: pytest.MonkeyPatch
) -> None:
    trigger = _edge("eid_new", "2026-05-10")
    sib = _edge("eid_old", "2026-04-01")
    payload = (
        '```json\n{"decisions": [{"sibling_edge_id": "eid_old", '
        '"decision": "coexist", "reason": "diff"}]}\n```'
    )

    client = MagicMock()
    client.invoke.return_value = _stub_llm_response(payload)
    monkeypatch.setattr("pearscarf.curation.get_llm_client", lambda *a, **kw: client)

    decisions = curation._judge_supersession(trigger, [sib])
    assert decisions == [{"sibling_edge_id": "eid_old", "decision": "coexist", "reason": "diff"}]


def test_judge_supersession_returns_empty_on_non_json(
    curation: Curation, monkeypatch: pytest.MonkeyPatch
) -> None:
    trigger = _edge("eid_new", "2026-05-10")
    sib = _edge("eid_old", "2026-04-01")

    client = MagicMock()
    client.invoke.return_value = _stub_llm_response("I'm not sure how to judge this")
    monkeypatch.setattr("pearscarf.curation.get_llm_client", lambda *a, **kw: client)

    assert curation._judge_supersession(trigger, [sib]) == []


def test_judge_supersession_returns_empty_when_decisions_not_a_list(
    curation: Curation, monkeypatch: pytest.MonkeyPatch
) -> None:
    trigger = _edge("eid_new", "2026-05-10")
    sib = _edge("eid_old", "2026-04-01")

    client = MagicMock()
    client.invoke.return_value = _stub_llm_response('{"decisions": "wrong shape"}')
    monkeypatch.setattr("pearscarf.curation.get_llm_client", lambda *a, **kw: client)

    assert curation._judge_supersession(trigger, [sib]) == []


# ---- _scan_superseded ----


def test_scan_superseded_no_new_edges_returns_zero(
    curation: Curation, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pearscarf.curation.graph.get_edges_by_source_record", lambda _: [])
    assert curation._scan_superseded("record_xyz") == 0


def test_scan_superseded_no_siblings_returns_zero(
    curation: Curation, monkeypatch: pytest.MonkeyPatch
) -> None:
    new_edge = _edge("eid_new", "2026-05-10")
    monkeypatch.setattr("pearscarf.curation.graph.get_edges_by_source_record", lambda _: [new_edge])
    monkeypatch.setattr("pearscarf.curation.graph.get_supersession_siblings", lambda *a, **kw: [])
    mark_called: list[Any] = []
    monkeypatch.setattr(
        "pearscarf.curation.graph.mark_fact_stale",
        lambda *a, **kw: mark_called.append((a, kw)),
    )
    assert curation._scan_superseded("record_xyz") == 0
    assert mark_called == []


def test_scan_superseded_stales_sibling_when_trigger_supersedes(
    curation: Curation, monkeypatch: pytest.MonkeyPatch
) -> None:
    new_edge = _edge("eid_new", "2026-05-10")
    sibling = _edge("eid_old", "2026-04-01")

    monkeypatch.setattr("pearscarf.curation.graph.get_edges_by_source_record", lambda _: [new_edge])
    monkeypatch.setattr(
        "pearscarf.curation.graph.get_supersession_siblings", lambda *a, **kw: [sibling]
    )

    client = MagicMock()
    client.invoke.return_value = _stub_llm_response(
        '{"decisions": [{"sibling_edge_id": "eid_old", '
        '"decision": "trigger_supersedes_sibling", "reason": "later term"}]}'
    )
    monkeypatch.setattr("pearscarf.curation.get_llm_client", lambda *a, **kw: client)

    stale_calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        "pearscarf.curation.graph.mark_fact_stale",
        lambda edge_id, replaced_by_id=None: stale_calls.append((edge_id, replaced_by_id)),
    )

    n = curation._scan_superseded("record_xyz")
    assert n == 1
    assert stale_calls == [("eid_old", "eid_new")]


def test_scan_superseded_stales_trigger_when_sibling_supersedes(
    curation: Curation, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Backfill case: trigger is older than an existing sibling on the same slot.
    new_edge = _edge("eid_new", "2024-01-01", fact="Alice promoted to Director")
    sibling = _edge("eid_sib", "2025-09-01", fact="Alice promoted to VP")

    monkeypatch.setattr("pearscarf.curation.graph.get_edges_by_source_record", lambda _: [new_edge])
    monkeypatch.setattr(
        "pearscarf.curation.graph.get_supersession_siblings", lambda *a, **kw: [sibling]
    )

    client = MagicMock()
    client.invoke.return_value = _stub_llm_response(
        '{"decisions": [{"sibling_edge_id": "eid_sib", '
        '"decision": "sibling_supersedes_trigger", "reason": "later role"}]}'
    )
    monkeypatch.setattr("pearscarf.curation.get_llm_client", lambda *a, **kw: client)

    stale_calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        "pearscarf.curation.graph.mark_fact_stale",
        lambda edge_id, replaced_by_id=None: stale_calls.append((edge_id, replaced_by_id)),
    )

    n = curation._scan_superseded("record_xyz")
    assert n == 1
    assert stale_calls == [("eid_new", "eid_sib")]


def test_scan_superseded_picks_freshest_sibling_when_multiple_supersede_trigger(
    curation: Curation, monkeypatch: pytest.MonkeyPatch
) -> None:
    new_edge = _edge("eid_new", "2024-01-01")
    older_super = _edge("eid_sib_a", "2025-01-01")
    fresher_super = _edge("eid_sib_b", "2026-01-01")

    monkeypatch.setattr("pearscarf.curation.graph.get_edges_by_source_record", lambda _: [new_edge])
    monkeypatch.setattr(
        "pearscarf.curation.graph.get_supersession_siblings",
        lambda *a, **kw: [older_super, fresher_super],
    )

    client = MagicMock()
    client.invoke.return_value = _stub_llm_response(
        '{"decisions": ['
        '{"sibling_edge_id": "eid_sib_a", "decision": "sibling_supersedes_trigger", "reason": "newer"},'
        '{"sibling_edge_id": "eid_sib_b", "decision": "sibling_supersedes_trigger", "reason": "newest"}'
        "]}"
    )
    monkeypatch.setattr("pearscarf.curation.get_llm_client", lambda *a, **kw: client)

    stale_calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        "pearscarf.curation.graph.mark_fact_stale",
        lambda edge_id, replaced_by_id=None: stale_calls.append((edge_id, replaced_by_id)),
    )

    n = curation._scan_superseded("record_xyz")
    assert n == 1
    assert stale_calls == [("eid_new", "eid_sib_b")]


def test_scan_superseded_skips_coexist_decisions(
    curation: Curation, monkeypatch: pytest.MonkeyPatch
) -> None:
    new_edge = _edge("eid_new", "2026-05-10")
    sibling = _edge("eid_old", "2026-04-01")

    monkeypatch.setattr("pearscarf.curation.graph.get_edges_by_source_record", lambda _: [new_edge])
    monkeypatch.setattr(
        "pearscarf.curation.graph.get_supersession_siblings", lambda *a, **kw: [sibling]
    )

    client = MagicMock()
    client.invoke.return_value = _stub_llm_response(
        '{"decisions": [{"sibling_edge_id": "eid_old", '
        '"decision": "coexist", "reason": "different topic"}]}'
    )
    monkeypatch.setattr("pearscarf.curation.get_llm_client", lambda *a, **kw: client)

    stale_calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        "pearscarf.curation.graph.mark_fact_stale",
        lambda edge_id, replaced_by_id=None: stale_calls.append((edge_id, replaced_by_id)),
    )

    n = curation._scan_superseded("record_xyz")
    assert n == 0
    assert stale_calls == []


def test_scan_superseded_passes_trigger_as_first_section_in_judge_input(
    curation: Curation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Trigger is always the trigger, regardless of source_at relative to siblings."""
    new_edge = _edge("eid_new", "2026-04-01", fact="trigger fact")
    sibling = _edge("eid_sib", "2026-05-15", fact="sibling fact")

    monkeypatch.setattr("pearscarf.curation.graph.get_edges_by_source_record", lambda _: [new_edge])
    monkeypatch.setattr(
        "pearscarf.curation.graph.get_supersession_siblings", lambda *a, **kw: [sibling]
    )

    invoke_inputs: list[str] = []

    def _capture_invoke(**kwargs: Any) -> Any:
        invoke_inputs.append(kwargs["messages"][0]["content"])
        return _stub_llm_response('{"decisions": []}')

    client = MagicMock()
    client.invoke.side_effect = _capture_invoke
    monkeypatch.setattr("pearscarf.curation.get_llm_client", lambda *a, **kw: client)
    monkeypatch.setattr("pearscarf.curation.graph.mark_fact_stale", lambda *a, **kw: None)

    curation._scan_superseded("record_xyz")

    assert len(invoke_inputs) == 1
    text = invoke_inputs[0]
    trigger_section, _, siblings_section = text.partition("EXISTING SIBLINGS")
    assert "edge_id: eid_new" in trigger_section
    assert "edge_id: eid_sib" in siblings_section


def test_scan_superseded_ignores_unknown_sibling_id_in_decision(
    curation: Curation, monkeypatch: pytest.MonkeyPatch
) -> None:
    new_edge = _edge("eid_new", "2026-05-10")
    sibling = _edge("eid_old", "2026-04-01")

    monkeypatch.setattr("pearscarf.curation.graph.get_edges_by_source_record", lambda _: [new_edge])
    monkeypatch.setattr(
        "pearscarf.curation.graph.get_supersession_siblings", lambda *a, **kw: [sibling]
    )

    client = MagicMock()
    client.invoke.return_value = _stub_llm_response(
        '{"decisions": [{"sibling_edge_id": "eid_unknown", '
        '"decision": "trigger_supersedes_sibling", "reason": "judge confused"}]}'
    )
    monkeypatch.setattr("pearscarf.curation.get_llm_client", lambda *a, **kw: client)

    stale_calls: list[Any] = []
    monkeypatch.setattr(
        "pearscarf.curation.graph.mark_fact_stale",
        lambda *a, **kw: stale_calls.append((a, kw)),
    )

    n = curation._scan_superseded("record_xyz")
    assert n == 0
    assert stale_calls == []


def test_scan_superseded_passes_record_id_as_exclude_record_id(
    curation: Curation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Curator must pass record_id to get_supersession_siblings so the record's
    own edges don't become candidate supersedors of each other."""
    new_edge = _edge("eid_new", "2026-05-10")

    monkeypatch.setattr("pearscarf.curation.graph.get_edges_by_source_record", lambda _: [new_edge])

    sibling_calls: list[dict] = []

    def _capture(edge_id, exclude_record_id=None):
        sibling_calls.append({"edge_id": edge_id, "exclude_record_id": exclude_record_id})
        return []

    monkeypatch.setattr("pearscarf.curation.graph.get_supersession_siblings", _capture)
    monkeypatch.setattr("pearscarf.curation.graph.mark_fact_stale", lambda *a, **kw: None)

    curation._scan_superseded("record_xyz")

    assert sibling_calls == [{"edge_id": "eid_new", "exclude_record_id": "record_xyz"}]
