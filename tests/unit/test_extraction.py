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


# ---- _process_record: intent records skip extraction ----


def test_process_record_skips_intent(
    monkeypatch: pytest.MonkeyPatch, patched_conn: MagicMock
) -> None:
    """Records with op_area=intent are marked indexed without running the extractor."""
    extractor_called = {"value": False}

    def fake_run_extractor(self, record, content):
        extractor_called["value"] = True
        return None

    monkeypatch.setattr(Extraction, "_run_extractor_agent", fake_run_extractor)

    record = {
        "id": "r_intent",
        "type": "record",
        "metadata": {"op_area": "intent"},
        "content": "Title: foo\n\nId: foo\nDate: 2026-05-12\n",
    }
    Extraction()._process_record(record)

    assert extractor_called["value"] is False
    # _mark_indexed runs an UPDATE on the records table.
    sql_calls = [c.args[0] for c in patched_conn.execute.call_args_list]
    assert any("UPDATE records SET indexed = TRUE" in s for s in sql_calls)


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


# ---- _commit_extraction: source_at threading ----


def test_commit_extraction_uses_metadata_source_at(monkeypatch: pytest.MonkeyPatch) -> None:
    """metadata.source_at flows through to graph.create_fact_edge as source_at."""
    # Track what source_at value is passed to create_fact_edge
    captured_source_at = {"value": None}

    def mock_create_fact_edge(*args, **kwargs):
        captured_source_at["value"] = kwargs.get("source_at")

    # Mock graph functions
    monkeypatch.setattr("pearscarf.extraction.graph.find_exact_dup_edge", lambda *a, **k: None)
    monkeypatch.setattr("pearscarf.extraction.graph.create_fact_edge", mock_create_fact_edge)
    monkeypatch.setattr("pearscarf.extraction.graph.get_or_create_day", lambda d: "day_123")
    monkeypatch.setattr("pearscarf.extraction.graph.utc_to_local_date", lambda dt: "2026-05-14")

    # Mock _commit_entities to return a simple entity_id_map
    def mock_commit_entities(self, record, extraction):
        return {"Alice": "ent_alice"}

    monkeypatch.setattr(Extraction, "_commit_entities", mock_commit_entities)

    record = {
        "id": "rec_1",
        "type": "record",
        "metadata": {"source_at": "2026-05-14T10:00:00Z"},
        "created_at": "2026-05-14T12:00:00Z",
    }
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

    Extraction()._commit_extraction(record, extraction)

    # Assert: source_at passed to create_fact_edge should be metadata.source_at
    assert captured_source_at["value"] == "2026-05-14T10:00:00Z"


def test_commit_extraction_falls_back_to_created_at_when_metadata_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When metadata.source_at is absent, fallback chain uses record.created_at."""
    captured_source_at = {"value": None}

    def mock_create_fact_edge(*args, **kwargs):
        captured_source_at["value"] = kwargs.get("source_at")

    monkeypatch.setattr("pearscarf.extraction.graph.find_exact_dup_edge", lambda *a, **k: None)
    monkeypatch.setattr("pearscarf.extraction.graph.create_fact_edge", mock_create_fact_edge)
    monkeypatch.setattr("pearscarf.extraction.graph.get_or_create_day", lambda d: "day_123")
    monkeypatch.setattr("pearscarf.extraction.graph.utc_to_local_date", lambda dt: "2026-05-14")

    def mock_commit_entities(self, record, extraction):
        return {"Alice": "ent_alice"}

    monkeypatch.setattr(Extraction, "_commit_entities", mock_commit_entities)

    record = {
        "id": "rec_2",
        "type": "record",
        "metadata": {},  # No source_at here
        "created_at": "2026-05-14T12:00:00Z",
    }
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

    Extraction()._commit_extraction(record, extraction)

    # Assert: source_at should fall back to record.created_at
    assert captured_source_at["value"] == "2026-05-14T12:00:00Z"
