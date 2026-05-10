"""Tests for `pearscarf.experts.ingest` — file-based ingestion tools."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pearscarf.experts.ingest import (
    ParseRecordFileTool,
    ParseSeedTool,
    _load_json_records,
)

# ---- _load_json_records ----


def test_load_json_records_single_file_dict(tmp_path: Path) -> None:
    f = tmp_path / "rec.json"
    f.write_text(json.dumps({"id": "x"}))
    assert _load_json_records(str(f)) == [{"id": "x"}]


def test_load_json_records_single_file_list(tmp_path: Path) -> None:
    f = tmp_path / "recs.json"
    f.write_text(json.dumps([{"id": "1"}, {"id": "2"}]))
    assert _load_json_records(str(f)) == [{"id": "1"}, {"id": "2"}]


def test_load_json_records_dir_concatenates(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(json.dumps({"id": "a"}))
    (tmp_path / "b.json").write_text(json.dumps([{"id": "b1"}, {"id": "b2"}]))
    (tmp_path / "skip.txt").write_text("ignored")
    result = _load_json_records(str(tmp_path))
    assert isinstance(result, list)
    assert {r["id"] for r in result} == {"a", "b1", "b2"}


def test_load_json_records_missing_path_returns_error() -> None:
    out = _load_json_records("/nonexistent/path/x.json")
    assert isinstance(out, str)
    assert "not found" in out


# ---- ParseSeedTool ----


def test_parse_seed_tool_saves_and_returns_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = tmp_path / "seed.md"
    seed.write_text("Title: x\n\nFoo")
    monkeypatch.setattr("pearscarf.storage.store.save_ingest", lambda **kw: "ingest_001")
    out = ParseSeedTool().execute(file_path=str(seed))
    assert "ingest_001" in out


def test_parse_seed_tool_missing_file_returns_error(tmp_path: Path) -> None:
    out = ParseSeedTool().execute(file_path=str(tmp_path / "nope.md"))
    assert "not found" in out


def test_parse_seed_tool_empty_file_returns_error(tmp_path: Path) -> None:
    f = tmp_path / "blank.md"
    f.write_text("   \n\n   ")
    out = ParseSeedTool().execute(file_path=str(f))
    assert "empty" in out


# ---- ParseRecordFileTool ----


def test_parse_record_file_no_expert_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "rec.json"
    f.write_text(json.dumps([{"id": "1"}]))
    registry = MagicMock()
    registry.get_connect.return_value = None
    monkeypatch.setattr("pearscarf.registry.get_registry", lambda: registry)
    out = ParseRecordFileTool().execute(file_path=str(f), record_type="email")
    assert "no expert registered" in out


def test_parse_record_file_saves_records_via_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "rec.json"
    f.write_text(json.dumps([{"id": "1"}, {"id": "2"}]))

    connect = MagicMock()
    connect.ingest_record.side_effect = ["rec_a", None]  # second is duplicate
    registry = MagicMock()
    registry.get_connect.return_value = connect
    monkeypatch.setattr("pearscarf.registry.get_registry", lambda: registry)
    monkeypatch.setattr("pearscarf.storage.store.mark_relevant", lambda rid: None)

    out = ParseRecordFileTool().execute(file_path=str(f), record_type="email")
    assert "Saved 1 email" in out
    assert "Skipped 1 duplicate" in out
    assert "rec_a" in out


def test_parse_record_file_empty_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "empty.json"
    f.write_text(json.dumps([]))
    out = ParseRecordFileTool().execute(file_path=str(f), record_type="email")
    assert "no records found" in out
