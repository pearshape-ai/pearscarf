"""Tests for `pearscarf.expert_context` — storage/bus/log wrappers + factory."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pearscarf import expert_context as ec

# ---- PearscarfStorage ----


def test_storage_save_record_returns_none_when_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pearscarf.storage.store.save_record", lambda **k: None)
    storage = ec.PearscarfStorage("gm", "0.1.0")
    assert storage.save_record(record_type="email", raw="x") is None


def test_storage_save_record_explicit_classification_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_calls: list = []
    monkeypatch.setattr("pearscarf.storage.store.save_record", lambda **k: "rec_1")
    monkeypatch.setattr(
        "pearscarf.storage.store.set_classification",
        lambda rid, cl: set_calls.append((rid, cl)),
    )
    storage = ec.PearscarfStorage("gm", "0.1.0", relevancy_policy="required")
    storage.save_record(record_type="email", raw="x", classification="noise")
    assert set_calls == [("rec_1", "noise")]


def test_storage_save_record_skip_policy_marks_relevant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_calls: list = []
    monkeypatch.setattr("pearscarf.storage.store.save_record", lambda **k: "rec_2")
    monkeypatch.setattr(
        "pearscarf.storage.store.set_classification",
        lambda rid, cl: set_calls.append((rid, cl)),
    )
    storage = ec.PearscarfStorage("ls", relevancy_policy="skip")
    storage.save_record(record_type="issue", raw="x")
    assert set_calls == [("rec_2", "relevant")]


def test_storage_save_record_required_policy_marks_pending_triage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_calls: list = []
    monkeypatch.setattr("pearscarf.storage.store.save_record", lambda **k: "rec_3")
    monkeypatch.setattr(
        "pearscarf.storage.store.set_classification",
        lambda rid, cl: set_calls.append((rid, cl)),
    )
    storage = ec.PearscarfStorage("gm", relevancy_policy="required")
    storage.save_record(record_type="email", raw="x")
    assert set_calls == [("rec_3", "pending_triage")]


def test_storage_get_record_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pearscarf.storage.store.get_record", lambda rid: {"id": rid})
    assert ec.PearscarfStorage("ls").get_record("rec_1") == {"id": "rec_1"}


# ---- PearscarfBus ----


def test_bus_send_fills_in_from_agent() -> None:
    inner = MagicMock()
    bus = ec.PearscarfBus(inner, "linearscarf")
    bus.send("ses_1", "assistant", "hello")
    inner.send.assert_called_once_with(
        session_id="ses_1",
        from_agent="linearscarf",
        to_agent="assistant",
        content="hello",
    )


def test_bus_create_session_uses_expert_name() -> None:
    inner = MagicMock()
    inner.create_session.return_value = "ses_42"
    bus = ec.PearscarfBus(inner, "linearscarf")
    assert bus.create_session("daily") == "ses_42"
    inner.create_session.assert_called_once_with("linearscarf", "daily")


def test_bus_subscribe_stores_handler() -> None:
    bus = ec.PearscarfBus(MagicMock(), "x")
    handler = lambda msg: msg  # noqa: E731
    bus.subscribe(handler)
    assert bus._handler is handler


# ---- _load_expert_env ----


def test_load_expert_env_reads_kv_pairs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    (env_dir / ".gm.env").write_text("FOO=bar\n# comment\nBAZ=qux\nblanks ignored\n")
    monkeypatch.setattr("pearscarf.config.EXPERTS_DIR", str(tmp_path / "experts"))
    config = ec._load_expert_env("gm")
    assert config == {"FOO": "bar", "BAZ": "qux"}


def test_load_expert_env_missing_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pearscarf.config.EXPERTS_DIR", str(tmp_path / "experts"))
    assert ec._load_expert_env("nonexistent") == {}


# ---- build_context ----


def test_build_context_returns_expert_context_with_all_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_expert = MagicMock()
    fake_expert.relevancy_check = "skip"
    registry = MagicMock()
    registry.get_by_name.return_value = fake_expert
    monkeypatch.setattr("pearscarf.registry.get_registry", lambda: registry)

    bus = MagicMock()
    ctx = ec.build_context("ls", bus, config={"FOO": "bar"}, expert_version="0.1.0")
    assert ctx.expert_name == "ls"
    assert ctx.config == {"FOO": "bar"}
    assert isinstance(ctx.bus, ec.PearscarfBus)
    assert isinstance(ctx.storage, ec.PearscarfStorage)
    assert isinstance(ctx.log, ec.PearscarfLog)
