"""Tests for `pearscarf.interface.cli_memory` — memory inspection subcommands."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

import pearscarf.interface.cli_memory  # noqa: F401 — registers commands on the cli group
from pearscarf.interface.cli import cli
from pearscarf.interface.cli_memory import (
    format_entity,
    format_graph_stats,
    format_memory_list,
    format_record_memories,
    format_search_results,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---- formatters (pure) ----


def test_format_memory_list_empty_returns_no_memories_message() -> None:
    assert format_memory_list([]) == ["No memories found."]


def test_format_memory_list_renders_entries() -> None:
    out = format_memory_list([{"name": "Alice", "entity_type": "person", "id": "n1"}])
    assert any("Alice" in line for line in out)
    assert any("person" in line for line in out)
    assert any("n1" in line for line in out)


def test_format_search_results_empty() -> None:
    assert format_search_results([]) == ["No results found."]


def test_format_search_results_includes_score_and_record_id() -> None:
    out = format_search_results([{"text": "hi", "score": 0.876, "metadata": {"record_id": "r1"}}])
    assert any("0.876" in line for line in out)
    assert any("r1" in line for line in out)


def test_format_entity_not_found() -> None:
    assert format_entity(None) == ["Entity not found."]


def test_format_entity_with_facts_and_connections() -> None:
    out = format_entity(
        {
            "name": "Alice",
            "type": "person",
            "facts": [
                {
                    "edge_label": "AFFILIATED",
                    "value": "works at Acme",
                    "source_record": "rec_1",
                    "source_at": "2026-01-15",
                }
            ],
            "connections": [{"to_entity": "Acme", "relationship": "AFFILIATED"}],
        }
    )
    assert any("Alice" in line for line in out)
    assert any("works at Acme" in line for line in out)
    assert any("Acme" in line for line in out)


def test_format_graph_stats_renders_counts() -> None:
    out = format_graph_stats(
        {
            "total_entities": 10,
            "total_facts": 25,
            "current_facts": 20,
            "entity_counts": {"person": 7},
            "edge_label_counts": {"AFFILIATED": 12},
        }
    )
    assert any("Entities: 10" in line for line in out)
    assert any("20 current, 25 total" in line for line in out)
    assert any("AFFILIATED: 12" in line for line in out)


def test_format_record_memories_empty() -> None:
    assert format_record_memories([]) == ["No memories found for this record."]


# ---- CliRunner ----


def test_memory_search_invokes_search_helper(runner: CliRunner) -> None:
    with patch(
        "pearscarf.interface.cli_memory._search",
        return_value=[{"text": "hi", "score": 0.5, "metadata": {}}],
    ):
        result = runner.invoke(cli, ["memory", "search", "x"])
    assert result.exit_code == 0
    assert "hi" in result.output


def test_memory_entity_invokes_get_entity_helper(runner: CliRunner) -> None:
    with patch(
        "pearscarf.interface.cli_memory._get_entity",
        return_value={"name": "Alice", "type": "person", "facts": [], "connections": []},
    ):
        result = runner.invoke(cli, ["memory", "entity", "Alice"])
    assert result.exit_code == 0
    assert "Alice" in result.output


def test_memory_graph_invokes_stats_helper(runner: CliRunner) -> None:
    with patch(
        "pearscarf.interface.cli_memory._graph_stats",
        return_value={"total_entities": 5, "total_facts": 8},
    ):
        result = runner.invoke(cli, ["memory", "graph"])
    assert result.exit_code == 0
    assert "Entities: 5" in result.output


def test_memory_record_invokes_record_helper(runner: CliRunner) -> None:
    with patch("pearscarf.interface.cli_memory._get_memories_for_record", return_value=[]):
        result = runner.invoke(cli, ["memory", "record", "rec_1"])
    assert result.exit_code == 0
    assert "No memories" in result.output
