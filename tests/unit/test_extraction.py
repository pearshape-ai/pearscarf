"""Tests for `pearscarf.extraction` — extraction loop, validation, commit shaping."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from pearscarf.extraction import Extraction, SaveExtractionTool


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

    monkeypatch.setattr("pearscarf.extraction._get_conn", _fake_get_conn)
    return conn


# ---- SaveExtractionTool ----


def test_save_extraction_tool_records_result() -> None:
    tool = SaveExtractionTool()
    out = tool.execute(entities=[{"name": "x"}], facts=[{"fact": "y"}])
    assert "saved" in out.lower()
    assert tool.result == {"entities": [{"name": "x"}], "facts": [{"fact": "y"}]}


def test_save_extraction_tool_default_empty_lists() -> None:
    tool = SaveExtractionTool()
    tool.execute()
    assert tool.result == {"entities": [], "facts": []}


# ---- _build_content ----


def test_build_content_prefers_content_over_raw() -> None:
    ext = Extraction()
    assert ext._build_content({"content": "C", "raw": "R"}) == "C"


def test_build_content_falls_back_to_raw() -> None:
    ext = Extraction()
    assert ext._build_content({"content": "", "raw": "R"}) == "R"


def test_build_content_default_when_both_empty() -> None:
    ext = Extraction()
    assert ext._build_content({}) == "(no content)"


# ---- _validate_extraction ----


def _ext(facts=None, entities=None):
    return {"entities": entities or [], "facts": facts or []}


def test_validate_extraction_invalid_edge_label_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pearscarf.extraction.graph.FACT_CATEGORIES",
        {"AFFILIATED": ["employee"], "ASSERTED": [], "TRANSITIONED": []},
    )
    record = {"content": "Alice works at Acme.", "id": "rec_1"}
    extraction = _ext(
        entities=[{"name": "Alice", "type": "person", "resolved_to": "new"}],
        facts=[
            {
                "edge_label": "BOGUS",
                "fact_type": "x",
                "fact": "Alice works at Acme.",
                "from_entity": "Alice",
                "to_entity": None,
                "confidence": "stated",
            }
        ],
    )
    errors = Extraction()._validate_extraction(record, extraction)
    assert any("Invalid edge_label" in e for e in errors)


def test_validate_extraction_unknown_from_entity_flagged() -> None:
    record = {"content": "Alice works at Acme.", "id": "r"}
    extraction = _ext(
        entities=[{"name": "Alice", "type": "person", "resolved_to": "new"}],
        facts=[
            {
                "edge_label": "AFFILIATED",
                "fact_type": "employee",
                "fact": "Alice works at Acme.",
                "from_entity": "Bob",
                "to_entity": None,
                "confidence": "stated",
            }
        ],
    )
    errors = Extraction()._validate_extraction(record, extraction)
    assert any("unknown from_entity" in e for e in errors)


def test_validate_extraction_low_grounding_flagged() -> None:
    record = {"content": "Some unrelated text.", "id": "r"}
    extraction = _ext(
        entities=[{"name": "Alice", "type": "person", "resolved_to": "new"}],
        facts=[
            {
                "edge_label": "AFFILIATED",
                "fact_type": "employee",
                "fact": "totally invented hallucinated never appears here",
                "from_entity": "Alice",
                "to_entity": None,
                "confidence": "stated",
            }
        ],
    )
    errors = Extraction()._validate_extraction(record, extraction)
    assert any("hallucinated" in e for e in errors)


def test_validate_extraction_clean_returns_empty() -> None:
    record = {"content": "Alice works at Acme.", "id": "r"}
    extraction = _ext(
        entities=[{"name": "Alice", "type": "person", "resolved_to": "new"}],
        facts=[
            {
                "edge_label": "AFFILIATED",
                "fact_type": "employee",
                "fact": "Alice works at Acme.",
                "from_entity": "Alice",
                "to_entity": None,
                "confidence": "stated",
            }
        ],
    )
    assert Extraction()._validate_extraction(record, extraction) == []


# ---- _commit_extraction op_area routing ----


def test_commit_extraction_uses_metadata_op_area(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_create_entity(et, name, md):
        return f"node_{name}"

    def fake_find_dup(*a, **k):
        return None

    def fake_create_edge(*a, **k):
        captured["op_area"] = k.get("op_area")
        return "edge-1"

    monkeypatch.setattr("pearscarf.extraction.graph.create_entity", fake_create_entity)
    monkeypatch.setattr("pearscarf.extraction.graph.find_exact_dup_edge", fake_find_dup)
    monkeypatch.setattr("pearscarf.extraction.graph.create_fact_edge", fake_create_edge)
    monkeypatch.setattr("pearscarf.extraction.graph.utc_to_local_date", lambda x: "2026-03-21")
    monkeypatch.setattr("pearscarf.extraction.graph.get_or_create_day", lambda d: "day-1")

    record = {
        "id": "r1",
        "type": "email",
        "metadata": {"op_area": "intention"},
        "created_at": "2026-03-21T00:00:00+00:00",
    }
    extraction = _ext(
        entities=[{"name": "Alice", "type": "person", "resolved_to": "new"}],
        facts=[
            {
                "edge_label": "ASSERTED",
                "fact_type": "commitment",
                "fact": "Alice will ship.",
                "from_entity": "Alice",
                "to_entity": None,
                "confidence": "stated",
            }
        ],
    )
    Extraction()._commit_extraction(record, extraction)
    assert captured["op_area"] == "intention"


def test_commit_extraction_default_op_area_is_reality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    monkeypatch.setattr("pearscarf.extraction.graph.create_entity", lambda *a, **k: "node_1")
    monkeypatch.setattr("pearscarf.extraction.graph.find_exact_dup_edge", lambda *a, **k: None)
    monkeypatch.setattr(
        "pearscarf.extraction.graph.create_fact_edge",
        lambda *a, **k: captured.setdefault("op_area", k.get("op_area")) or "e1",
    )
    monkeypatch.setattr("pearscarf.extraction.graph.utc_to_local_date", lambda x: "2026-03-21")
    monkeypatch.setattr("pearscarf.extraction.graph.get_or_create_day", lambda d: "day-1")

    record = {"id": "r1", "type": "email", "created_at": "2026-03-21T00:00:00+00:00"}
    extraction = _ext(
        entities=[{"name": "Alice", "type": "person", "resolved_to": "new"}],
        facts=[
            {
                "edge_label": "ASSERTED",
                "fact_type": "commitment",
                "fact": "Alice will ship.",
                "from_entity": "Alice",
                "to_entity": None,
                "confidence": "stated",
            }
        ],
    )
    Extraction()._commit_extraction(record, extraction)
    assert captured["op_area"] == "reality"


# ---- _embed_record error swallowing ----


def test_embed_record_swallows_qdrant_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pearscarf.extraction.vectorstore.add_record",
        MagicMock(side_effect=RuntimeError("qdrant down")),
    )
    Extraction()._embed_record({"id": "r1", "metadata": {}}, "content")
    # No raise = pass


# ---- _mark_indexed ----


def test_mark_indexed_executes_update(patched_conn: MagicMock) -> None:
    Extraction()._mark_indexed("rec_1")
    sql = patched_conn.execute.call_args.args[0]
    assert "UPDATE records SET indexed" in sql


# ---- _debug_write skipped when no debug dir ----


def test_debug_write_no_op_when_debug_dir_unset(tmp_path) -> None:
    ext = Extraction(debug_dir=None)
    ext._debug_write("rec_1", "name.md", "content")
    # Nothing should have been written anywhere; no exceptions.
    assert not list(tmp_path.iterdir())


def test_debug_write_writes_when_debug_dir_set(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    ext = Extraction(debug_dir=str(tmp_path))
    monkeypatch.setattr(ext, "_debug_folder_name", lambda rid: "folder")
    ext._debug_write("rec_1", "agent.md", "hello")
    assert (tmp_path / "folder" / "agent.md").read_text() == "hello"
