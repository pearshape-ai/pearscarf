"""Tests for `scripts/backfill_fact_embeddings.py` — the fact backfill loop.

The script isn't a package; load it by path. Only the pure `backfill` loop is
exercised here (no Neo4j / Qdrant) — it must embed each valid fact once, skip
rows missing an id or text, and return the embedded count.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backfill_fact_embeddings.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("backfill_fact_embeddings", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backfill_embeds_each_valid_fact_and_skips_empties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_module()
    calls: list[tuple] = []
    monkeypatch.setattr(
        "pearscarf.storage.vectorstore.add_fact",
        lambda fid, text, payload=None: calls.append((fid, text, payload)),
    )

    facts = [
        {
            "edge_id": "e1",
            "fact": "A",
            "edge_label": "ASSERTED",
            "fact_type": "update",
            "source_record": "r1",
        },
        {
            "edge_id": "e2",
            "fact": "B",
            "edge_label": "AFFILIATED",
            "fact_type": "employee",
            "source_record": "r2",
        },
        {"edge_id": "", "fact": "skip — no id"},
        {"edge_id": "e3", "fact": None},
    ]
    embedded = mod.backfill(facts)

    assert embedded == 2
    assert [c[0] for c in calls] == ["e1", "e2"]
    assert calls[1][2]["source_record"] == "r2"
