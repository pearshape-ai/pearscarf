"""Tests for `pearscarf.tracked_call` — observability wrapper."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from pearscarf import tracked_call as tc_mod
from pearscarf.agents.llm_client import LLMResponse, LLMUsage
from pearscarf.tracked_call import _to_jsonable

# ---- _to_jsonable ----


class _FakeSDKBlock:
    """Mimics an Anthropic SDK Pydantic block (TextBlock / ToolUseBlock)."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def model_dump(self) -> dict:
        return dict(self._payload)


def test_to_jsonable_converts_sdk_model_via_model_dump() -> None:
    block = _FakeSDKBlock({"type": "text", "text": "hello"})
    assert _to_jsonable(block) == {"type": "text", "text": "hello"}


def test_to_jsonable_walks_message_list_with_sdk_blocks() -> None:
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": [_FakeSDKBlock({"type": "text", "text": "back"})],
        },
    ]
    out = _to_jsonable(messages)
    # The whole thing must now be json-serializable.
    json.dumps(out)
    assert out[0] == {"role": "user", "content": "hi"}
    assert out[1] == {
        "role": "assistant",
        "content": [{"type": "text", "text": "back"}],
    }


def test_to_jsonable_passes_primitives_through() -> None:
    assert _to_jsonable("x") == "x"
    assert _to_jsonable(7) == 7
    assert _to_jsonable(None) is None
    assert _to_jsonable([1, 2, 3]) == [1, 2, 3]
    assert _to_jsonable({"a": 1}) == {"a": 1}


@pytest.fixture
def patched_conn(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    conn = MagicMock()
    conn.execute.return_value = MagicMock()
    conn.commit.return_value = None

    @contextmanager
    def _fake_get_conn():
        yield conn

    monkeypatch.setattr("pearscarf.tracked_call._get_conn", _fake_get_conn)
    return conn


@dataclass
class _FakeClient:
    provider_name: str = "anthropic"
    raise_on_invoke: bool = False
    response: LLMResponse = field(default_factory=lambda: LLMResponse(text="ok"))

    def invoke(self, **_kwargs):
        if self.raise_on_invoke:
            raise RuntimeError("boom")
        return self.response


def test_tracked_call_returns_client_response(patched_conn: MagicMock) -> None:
    client = _FakeClient()
    result = tc_mod.tracked_call(client, "agent_x", system="s", model="claude-opus-4-7")
    assert result is client.response


def test_tracked_call_writes_two_inserts(patched_conn: MagicMock) -> None:
    """Logs prompt body + llm_calls row per call."""
    client = _FakeClient()
    tc_mod.tracked_call(client, "agent_x", system="s", model="claude-opus-4-7")
    sqls = [c.args[0] for c in patched_conn.execute.call_args_list]
    assert any("INSERT INTO llm_prompts" in s for s in sqls)
    assert any("INSERT INTO llm_calls" in s for s in sqls)


def test_tracked_call_propagates_exception_and_logs_error(
    patched_conn: MagicMock,
) -> None:
    client = _FakeClient(raise_on_invoke=True)
    with pytest.raises(RuntimeError, match="boom"):
        tc_mod.tracked_call(client, "agent_x", system="s", model="claude-opus-4-7")
    # Even on raise, the error log row goes in
    sqls = [c.args[0] for c in patched_conn.execute.call_args_list]
    assert any("INSERT INTO llm_calls" in s for s in sqls)


def test_register_runtime_returns_uuid_and_inserts(patched_conn: MagicMock) -> None:
    rt_id = tc_mod.register_runtime("triage")
    assert isinstance(rt_id, str)
    assert len(rt_id) == 36  # uuid format
    sqls = [c.args[0] for c in patched_conn.execute.call_args_list]
    assert any("INSERT INTO runtimes" in s for s in sqls)


def test_mark_run_hit_ceiling_executes_update(patched_conn: MagicMock) -> None:
    tc_mod.mark_run_hit_ceiling("run-1")
    sql = patched_conn.execute.call_args.args[0]
    assert "UPDATE llm_calls SET stop_reason" in sql
    assert "turn_ceiling" in sql


def test_tracked_call_uses_response_usage_for_token_counts(
    patched_conn: MagicMock,
) -> None:
    response = LLMResponse(
        text="hi",
        stop_reason="end_turn",
        usage=LLMUsage(input_tokens=42, output_tokens=7, cache_read_tokens=3),
    )
    client = _FakeClient(response=response)
    tc_mod.tracked_call(client, "agent_x", system="s", model="claude-opus-4-7")
    insert_calls = [
        c for c in patched_conn.execute.call_args_list if "INSERT INTO llm_calls" in c.args[0]
    ]
    args = insert_calls[0].args[1]
    # input_tokens, output_tokens, cache_creation, cache_read positions vary;
    # assert presence in tuple.
    assert 42 in args
    assert 7 in args
    assert 3 in args
