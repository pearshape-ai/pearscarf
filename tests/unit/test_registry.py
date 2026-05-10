"""Tests for prompt-composition pieces of `pearscarf.registry.Registry`.

The Registry's __init__ loads experts from filesystem and DB. These tests
patch `_db_rows` to skip DB and point `experts_dir` at an empty tmp_path so
only internal experts (which declare no entity types) are present. That
isolates `schema_fragment` and `_render_deployment_section_seed` to the
input axes that matter — core entity files + deployment vocab.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pearscarf.deployment_vocab import reset_vocab
from pearscarf.registry import Registry


@pytest.fixture(autouse=True)
def _reset_vocab_cache() -> None:
    reset_vocab()


@pytest.fixture
def empty_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Registry:
    """Build a Registry with no DB load and an empty experts dir."""
    monkeypatch.setattr(Registry, "_db_rows", lambda self: [])
    return Registry(tmp_path)


# ---- _render_deployment_section_seed ----


def test_render_deployment_section_seed_empty_when_no_vocab(
    empty_registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEPLOYMENT_VOCAB_PATH", raising=False)
    assert empty_registry._render_deployment_section_seed() == ""


def test_render_deployment_section_seed_one_type_no_description(
    empty_registry: Registry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vocab_file = tmp_path / "vocab.yaml"
    vocab_file.write_text("entity_types:\n  - name: sub_system\n")
    monkeypatch.setenv("DEPLOYMENT_VOCAB_PATH", str(vocab_file))

    rendered = empty_registry._render_deployment_section_seed()
    assert "## sub_systems" in rendered
    assert "sub_system" in rendered
    assert ":Sub_system" in rendered  # Neo4j label hint


def test_render_deployment_section_seed_with_description(
    empty_registry: Registry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vocab_file = tmp_path / "vocab.yaml"
    vocab_file.write_text(
        "entity_types:\n  - name: sub_system\n    description: A deployed service.\n"
    )
    monkeypatch.setenv("DEPLOYMENT_VOCAB_PATH", str(vocab_file))

    rendered = empty_registry._render_deployment_section_seed()
    assert "A deployed service." in rendered


def test_render_deployment_section_seed_multiple_types_one_per_line(
    empty_registry: Registry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vocab_file = tmp_path / "vocab.yaml"
    vocab_file.write_text(
        "entity_types:\n  - name: sub_system\n  - name: machine\n",
    )
    monkeypatch.setenv("DEPLOYMENT_VOCAB_PATH", str(vocab_file))

    rendered = empty_registry._render_deployment_section_seed()
    lines = rendered.split("\n")
    assert len(lines) == 2
    assert any("sub_system" in line for line in lines)
    assert any("machine" in line for line in lines)


# ---- schema_fragment ----


def test_schema_fragment_starts_with_entity_types_heading(
    empty_registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEPLOYMENT_VOCAB_PATH", raising=False)
    fragment = empty_registry.schema_fragment()
    assert fragment.startswith("## Entity Types\n")


def test_schema_fragment_contains_canonical_core_types(
    empty_registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEPLOYMENT_VOCAB_PATH", raising=False)
    fragment = empty_registry.schema_fragment()
    # Core types ship as files in pearscarf/knowledge/core/entities/.
    # All four canonical types should be referenced by name.
    assert "**company**" in fragment
    assert "**event**" in fragment
    assert "**person**" in fragment
    assert "**project**" in fragment


def test_schema_fragment_appends_deployment_vocab_types(
    empty_registry: Registry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vocab_file = tmp_path / "vocab.yaml"
    vocab_file.write_text(
        "entity_types:\n  - name: sub_system\n    description: A deployed service.\n",
    )
    monkeypatch.setenv("DEPLOYMENT_VOCAB_PATH", str(vocab_file))

    fragment = empty_registry.schema_fragment()
    assert "**sub_system**" in fragment
    assert "A deployed service." in fragment


def test_schema_fragment_ends_with_normalization_block(
    empty_registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEPLOYMENT_VOCAB_PATH", raising=False)
    fragment = empty_registry.schema_fragment()
    # Normalization block ships at pearscarf/knowledge/core/normalization.md
    # and lives at the end per the function's contract.
    assert "Entity Name Normalization" in fragment
    # Sanity: the normalization heading is below the entity types list.
    norm_idx = fragment.index("Entity Name Normalization")
    types_idx = fragment.index("## Entity Types")
    assert norm_idx > types_idx


def test_schema_fragment_caches_result(
    empty_registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEPLOYMENT_VOCAB_PATH", raising=False)
    first = empty_registry.schema_fragment()
    second = empty_registry.schema_fragment()
    # Same Registry instance returns the same string from cache.
    assert first is second
