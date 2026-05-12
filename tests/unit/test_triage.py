"""Tests for `pearscarf.triage` — classification dispatch."""

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


def test_classify_tool_schema() -> None:
    tool = ClassifyTriageTool()
    assert tool.input_schema["properties"]["classification"]["enum"] == [
        store.RELEVANT,
        store.NOISE,
        store.UNCERTAIN,
    ]
    assert tool.input_schema["required"] == ["classification", "reasoning"]


def test_classify_tool_execute_records_result() -> None:
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


# ---- Triage._process ----


def _stub_prompt_loaders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(triage_mod, "load_prompt", lambda name: f"PROMPT[{name}]")
    monkeypatch.setattr(triage_mod, "load_onboarding_block", lambda: "ONBOARDING\n")
    monkeypatch.setattr(triage_mod, "load_relevancy_guidance", lambda en: None)


def test_process_writes_classification(
    monkeypatch: pytest.MonkeyPatch, patched_conn: MagicMock
) -> None:
    _stub_prompt_loaders(monkeypatch)

    captured: dict = {}

    class FakeAgent:
        def __init__(self, *a, **k):
            captured["registry"] = k.get("tool_registry") or (a[0] if a else None)

        def run(self, msg):
            classify = next(t for t in captured["registry"]._tools.values() if t.name == "classify")
            classify.execute(classification=store.RELEVANT, reasoning="r")

    monkeypatch.setattr(triage_mod, "TriageAgent", FakeAgent)

    set_calls: list = []
    monkeypatch.setattr(
        "pearscarf.storage.store.set_classification",
        lambda rid, cl: set_calls.append((rid, cl)),
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
