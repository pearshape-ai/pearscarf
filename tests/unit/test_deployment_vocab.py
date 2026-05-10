"""Tests for `pearscarf.deployment_vocab.get_vocab` — YAML → DeploymentVocab transformation."""

from __future__ import annotations

from pathlib import Path

import pytest

from pearscarf.deployment_vocab import (
    DeploymentVocab,
    EntityType,
    FactType,
    get_vocab,
    reset_vocab,
)


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    """Drop the module-level vocab cache before every test."""
    reset_vocab()


def _write_vocab(path: Path, content: str) -> None:
    path.write_text(content)


def test_unset_env_var_returns_empty_vocab(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEPLOYMENT_VOCAB_PATH", raising=False)
    vocab = get_vocab()
    assert vocab == DeploymentVocab()
    assert vocab.entity_types == []
    assert vocab.fact_types == {}


def test_entity_types_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vocab_file = tmp_path / "vocab.yaml"
    _write_vocab(
        vocab_file,
        """
entity_types:
  - name: sub_system
""",
    )
    monkeypatch.setenv("DEPLOYMENT_VOCAB_PATH", str(vocab_file))

    vocab = get_vocab()
    assert vocab.entity_types == [EntityType(name="sub_system")]
    assert vocab.fact_types == {}


def test_fact_types_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vocab_file = tmp_path / "vocab.yaml"
    _write_vocab(
        vocab_file,
        """
fact_types:
  AFFILIATED:
    - name: runs_on
""",
    )
    monkeypatch.setenv("DEPLOYMENT_VOCAB_PATH", str(vocab_file))

    vocab = get_vocab()
    assert vocab.entity_types == []
    assert vocab.fact_types == {"AFFILIATED": [FactType(name="runs_on")]}


def test_both_entity_and_fact_types(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vocab_file = tmp_path / "vocab.yaml"
    _write_vocab(
        vocab_file,
        """
entity_types:
  - name: sub_system

fact_types:
  AFFILIATED:
    - name: runs_on
""",
    )
    monkeypatch.setenv("DEPLOYMENT_VOCAB_PATH", str(vocab_file))

    vocab = get_vocab()
    assert vocab.entity_types == [EntityType(name="sub_system")]
    assert vocab.fact_types == {"AFFILIATED": [FactType(name="runs_on")]}


def test_entity_type_description_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vocab_file = tmp_path / "vocab.yaml"
    _write_vocab(
        vocab_file,
        """
entity_types:
  - name: sub_system
    description: A deployed service or component.
""",
    )
    monkeypatch.setenv("DEPLOYMENT_VOCAB_PATH", str(vocab_file))

    vocab = get_vocab()
    assert vocab.entity_types == [
        EntityType(name="sub_system", description="A deployed service or component."),
    ]


def test_fact_type_description_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vocab_file = tmp_path / "vocab.yaml"
    _write_vocab(
        vocab_file,
        """
fact_types:
  AFFILIATED:
    - name: runs_on
      description: A's operational substrate is B.
""",
    )
    monkeypatch.setenv("DEPLOYMENT_VOCAB_PATH", str(vocab_file))

    vocab = get_vocab()
    assert vocab.fact_types == {
        "AFFILIATED": [FactType(name="runs_on", description="A's operational substrate is B.")],
    }


def test_multiple_edge_labels_keyed_correctly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vocab_file = tmp_path / "vocab.yaml"
    _write_vocab(
        vocab_file,
        """
fact_types:
  AFFILIATED:
    - name: runs_on
    - name: component_of
  TRANSITIONED:
    - name: attribute_change
""",
    )
    monkeypatch.setenv("DEPLOYMENT_VOCAB_PATH", str(vocab_file))

    vocab = get_vocab()
    assert set(vocab.fact_types.keys()) == {"AFFILIATED", "TRANSITIONED"}
    assert vocab.fact_types["AFFILIATED"] == [
        FactType(name="runs_on"),
        FactType(name="component_of"),
    ]
    assert vocab.fact_types["TRANSITIONED"] == [FactType(name="attribute_change")]


def test_path_does_not_exist_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "nonexistent.yaml"
    monkeypatch.setenv("DEPLOYMENT_VOCAB_PATH", str(missing))

    with pytest.raises(FileNotFoundError, match="DEPLOYMENT_VOCAB_PATH"):
        get_vocab()
