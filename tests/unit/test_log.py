"""Tests for `pearscarf.log` — append-only log writer."""

from __future__ import annotations

from pathlib import Path

import pytest

from pearscarf import log


@pytest.fixture(autouse=True)
def _isolated_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-point the module-level paths at a tmp dir per test."""
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(log, "_LOGS_DIR", log_dir)
    monkeypatch.setattr(log, "_LOG_FILE", log_dir / "session.log")
    monkeypatch.setattr(log, "_initialized", False)


def _read_log() -> str:
    return log._LOG_FILE.read_text()


def test_write_creates_log_dir_and_appends_line() -> None:
    log.write("triage", "ses_001", "action", "starting")
    assert log._LOG_FILE.exists()
    content = _read_log()
    assert "[triage]" in content
    assert "[ses_001]" in content
    assert "[action]" in content
    assert "starting" in content


def test_write_uses_double_dash_for_missing_session() -> None:
    log.write("extraction", None, "warning", "no record")
    content = _read_log()
    assert "[--]" in content


def test_write_appends_multiple_lines() -> None:
    log.write("triage", "s1", "action", "first")
    log.write("triage", "s1", "action", "second")
    lines = _read_log().splitlines()
    assert len(lines) == 2
    assert "first" in lines[0]
    assert "second" in lines[1]
