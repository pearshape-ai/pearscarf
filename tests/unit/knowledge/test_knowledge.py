"""Tests for `pearscarf.knowledge` — prompt loader + onboarding block resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

import pearscarf.knowledge as knowledge


@pytest.fixture(autouse=True)
def _reset_onboarding_cache() -> None:
    """Drop the module-level onboarding cache before each test."""
    knowledge._onboarding_block = None
    knowledge._onboarding_source = None


# ---- load(name) ----


def test_load_named_prompt_reads_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONBOARDING_PROMPT_PATH", raising=False)
    content = knowledge.load("onboarding")
    assert content  # non-empty default ships with the repo


def test_load_with_override_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    override = tmp_path / "custom_onboarding.md"
    override.write_text("CUSTOM ONBOARDING TEXT")
    monkeypatch.setenv("ONBOARDING_PROMPT_PATH", str(override))

    assert knowledge.load("onboarding") == "CUSTOM ONBOARDING TEXT"


def test_load_with_override_pointing_to_missing_file_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "nonexistent.md"
    monkeypatch.setenv("ONBOARDING_PROMPT_PATH", str(missing))

    with pytest.raises(FileNotFoundError, match="ONBOARDING_PROMPT_PATH"):
        knowledge.load("onboarding")


def test_load_unknown_name_raises_key_error() -> None:
    with pytest.raises(KeyError):
        knowledge.load("does_not_exist")


# ---- load_onboarding_block ----


def test_load_onboarding_block_frames_default_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ONBOARDING_PROMPT_PATH", raising=False)
    block = knowledge.load_onboarding_block()
    assert block.startswith("## Onboarding\n\n")
    assert block.endswith("\n\n---\n\n")


def test_load_onboarding_block_uses_override_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "custom.md"
    override.write_text("INNER")
    monkeypatch.setenv("ONBOARDING_PROMPT_PATH", str(override))

    assert knowledge.load_onboarding_block() == "## Onboarding\n\nINNER\n\n---\n\n"


def test_load_onboarding_block_returns_empty_when_content_blank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "blank.md"
    override.write_text("   \n  \n")
    monkeypatch.setenv("ONBOARDING_PROMPT_PATH", str(override))

    assert knowledge.load_onboarding_block() == ""


# ---- onboarding_summary ----


def test_onboarding_summary_default_returns_label_and_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ONBOARDING_PROMPT_PATH", raising=False)
    label, count = knowledge.onboarding_summary()
    assert "default" in label
    assert count > 0


def test_onboarding_summary_with_override_label_includes_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "custom.md"
    override.write_text("HELLO")
    monkeypatch.setenv("ONBOARDING_PROMPT_PATH", str(override))

    label, count = knowledge.onboarding_summary()
    assert "override" in label
    assert str(override) in label
    assert count > 0


def test_onboarding_summary_blank_content_marks_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "blank.md"
    override.write_text("")
    monkeypatch.setenv("ONBOARDING_PROMPT_PATH", str(override))

    label, count = knowledge.onboarding_summary()
    assert "(empty)" in label
    assert count == 0
