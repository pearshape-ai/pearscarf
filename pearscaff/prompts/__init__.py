"""Prompt loader — reads system prompts from markdown files."""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def load(name: str) -> str:
    """Load a prompt by name. Returns the file content as a string."""
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text()
