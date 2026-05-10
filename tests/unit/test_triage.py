"""Tests for `pearscarf.triage` — classification dispatch + op_area inference."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from pearscarf import triage as triage_mod
from pearscarf.storage import store
from pearscarf.triage import ClassifyTriageTool, Triage


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

    monkeypatch.setattr("pearscarf.triage._get_conn", _fake_get_conn)
    return conn


# ---- ClassifyTriageTool ----


def test_classify_tool_schema_omits_op_area_by_default() -> None:
    tool = ClassifyTriageTool()
    assert "op_area" not in tool.input_schema["properties"]
    assert "op_area" not in tool.input_schema["required"]


def test_classify_tool_schema_includes_op_area_when_inferred() -> None:
    tool = ClassifyTriageTool(infer_op_area=True)
    assert "op_area" in tool.input_schema["properties"]
    assert "op_area" in tool.input_schema["required"]


def test_classify_tool_execute_records_result() -> None:
    tool = ClassifyTriageTool(infer_op_area=True)
    tool.execute(classification="relevant", reasoning="why", op_area="reality")
    assert tool.result == {
        "classification": "relevant",
        "reasoning": "why",
        "op_area": "reality",
    }


def test_classify_tool_execute_omits_op_area_when_not_inferred() -> None:
    tool = ClassifyTriageTool()
    tool.execute(classification="noise", reasoning="trivial")
    assert tool.result == {"classification": "noise", "reasoning": "trivial"}


# ---- Triage._claim_one ----


def test_claim_one_returns_dict_when_row_present(patched_conn: MagicMock) -> None:
    row = {"id": "rec_1", "type": "email", "metadata": None, "expert_name": "gm"}
    patched_conn.execute.return_value.fetchone.return_value = row
    result = Triage()._claim_one()
    assert result == row


def test_claim_one_returns_none_when_queue_empty(patched_conn: MagicMock) -> None:
    patched_conn.execute.return_value.fetchone.return_value = None
    assert Triage()._claim_one() is None


# ---- Triage._reset_stale_triaging ----


def test_reset_stale_triaging_runs_update(patched_conn: MagicMock) -> None:
    patched_conn.execute.return_value.fetchall.return_value = [{"id": "r1"}]
    Triage()._reset_stale_triaging()
    sql = patched_conn.execute.call_args.args[0]
    assert "UPDATE records SET classification" in sql


# ---- Triage._process: op_area branching ----


def _stub_prompt_loaders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(triage_mod, "load_prompt", lambda name: f"PROMPT[{name}]")
    monkeypatch.setattr(triage_mod, "load_onboarding_block", lambda: "ONBOARDING\n")
    monkeypatch.setattr(triage_mod, "load_relevancy_guidance", lambda en: None)


def test_process_explicit_op_area_skips_inference(
    monkeypatch: pytest.MonkeyPatch, patched_conn: MagicMock
) -> None:
    _stub_prompt_loaders(monkeypatch)

    captured: dict = {}

    class FakeAgent:
        def __init__(self, *a, **k):
            captured["registry"] = k.get("tool_registry") or (a[0] if a else None)

        def run(self, msg):
            # Simulate the agent calling classify with no op_area
            classify = next(t for t in captured["registry"]._tools.values() if t.name == "classify")
            classify.execute(classification=store.RELEVANT, reasoning="r")

    monkeypatch.setattr(triage_mod, "TriageAgent", FakeAgent)

    set_calls: list = []
    monkeypatch.setattr(
        "pearscarf.storage.store.set_classification",
        lambda rid, cl: set_calls.append((rid, cl)),
    )
    monkeypatch.setattr(
        "pearscarf.storage.store.set_op_area",
        lambda rid, op: set_calls.append(("op_area", rid, op)),
    )

    record = {
        "id": "rec_1",
        "type": "email",
        "content": "x",
        "metadata": {"op_area": "reality"},
        "expert_name": "gm",
    }
    Triage()._process(record)

    assert ("rec_1", store.RELEVANT) in set_calls
    # explicit op_area means no set_op_area write
    assert all(c[0] != "op_area" for c in set_calls)


def test_process_no_op_area_triggers_inference_path(
    monkeypatch: pytest.MonkeyPatch, patched_conn: MagicMock
) -> None:
    _stub_prompt_loaders(monkeypatch)

    captured: dict = {}

    class FakeAgent:
        def __init__(self, *a, **k):
            captured["registry"] = k.get("tool_registry") or a[0]

        def run(self, msg):
            classify = next(t for t in captured["registry"]._tools.values() if t.name == "classify")
            classify.execute(classification=store.RELEVANT, reasoning="r", op_area="intention")

    monkeypatch.setattr(triage_mod, "TriageAgent", FakeAgent)

    set_calls: list = []
    monkeypatch.setattr(
        "pearscarf.storage.store.set_classification",
        lambda rid, cl: set_calls.append((rid, cl)),
    )
    monkeypatch.setattr(
        "pearscarf.storage.store.set_op_area",
        lambda rid, op: set_calls.append(("op_area", rid, op)),
    )

    record = {"id": "rec_2", "type": "email", "content": "x", "metadata": {}, "expert_name": "gm"}
    Triage()._process(record)

    assert ("op_area", "rec_2", "intention") in set_calls


def test_process_marks_uncertain_when_classify_not_called(
    monkeypatch: pytest.MonkeyPatch, patched_conn: MagicMock
) -> None:
    _stub_prompt_loaders(monkeypatch)

    class FakeAgent:
        def __init__(self, *a, **k):
            pass

        def run(self, msg):
            pass  # never calls classify

    monkeypatch.setattr(triage_mod, "TriageAgent", FakeAgent)

    set_calls: list = []
    monkeypatch.setattr(
        "pearscarf.storage.store.set_classification",
        lambda rid, cl: set_calls.append((rid, cl)),
    )
    record = {
        "id": "rec_3",
        "type": "email",
        "content": "x",
        "metadata": {"op_area": "reality"},
        "expert_name": "gm",
    }
    Triage()._process(record)

    assert (record["id"], store.UNCERTAIN) in set_calls
