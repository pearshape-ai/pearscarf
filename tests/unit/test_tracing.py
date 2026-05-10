"""Tests for `pearscarf.tracing` — LangSmith decorator + span context managers."""

from __future__ import annotations

import pytest

from pearscarf import tracing


def test_traceable_when_disabled_returns_function_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tracing, "LANGSMITH_ENABLED", False)

    @tracing.traceable("foo")
    def fn(x):
        return x * 2

    assert fn(3) == 6


def test_traceable_when_enabled_calls_langsmith(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "LANGSMITH_ENABLED", True)
    import langsmith as _ls

    captured: dict = {}

    def fake_ls_traceable(*args, **kwargs):
        captured.update(kwargs)
        return lambda fn: fn

    monkeypatch.setattr(_ls, "traceable", fake_ls_traceable)

    @tracing.traceable("foo", run_type="tool", metadata={"k": "v"})
    def fn(x):
        return x

    assert fn(1) == 1
    assert captured["name"] == "foo"
    assert captured["run_type"] == "tool"
    assert captured["metadata"] == {"k": "v"}


def test_trace_span_when_disabled_yields_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "LANGSMITH_ENABLED", False)
    with tracing.trace_span("op") as span:
        assert span is None


def test_trace_child_when_parent_none_yields_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "LANGSMITH_ENABLED", True)
    with tracing.trace_child(None, "child") as ch:
        assert ch is None
