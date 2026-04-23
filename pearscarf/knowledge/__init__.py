"""Knowledge module — static prompt loader.

* `load(name)` — read a single named prompt. If the entry declares an
  override env var and it is set, read from that path instead of the
  shipped default. Used by agents for their own system prompts and by
  the Extraction consumer for the extractor agent's prompt.
* `load_onboarding_block()` — onboarding content wrapped in its header
  block, cached. Onboards PearScarf to the world it operates in.

Extraction prompt composition lives in `pearscarf.registry` —
it owns Layer 1 (`core_prompt`), Layer 2 (`schema_fragment`), and the
per-record `compose_prompt(record)` that joins them with Layer 3.
"""

from __future__ import annotations

import os
from pathlib import Path


KNOWLEDGE_DIR = Path(__file__).parent


# prompt name → (relative path under pearscarf/knowledge/, override env var)
_KNOWLEDGE_MAP: dict[str, tuple[str, str | None]] = {
    "assistant":        ("assistant/agent.md",          None),
    "retriever":        ("retriever/agent.md",          None),
    "ingest":           ("ingest/agent.md",             None),
    "extractor_agent":  ("extractor/extractor_agent.md", None),
    "seed_guidance":    ("ingest/seed_guidance.md",     None),
    "triage_agent":     ("triage/agent.md",             None),
    "onboarding":       ("onboarding.md",               "ONBOARDING_PROMPT_PATH"),
}


def load(name: str) -> str:
    """Load a prompt by name. Returns the file content as a string."""
    rel_path, override_env = _KNOWLEDGE_MAP[name]
    if override_env:
        override = os.getenv(override_env)
        if override:
            path = Path(override)
            if not path.is_file():
                raise FileNotFoundError(
                    f"{override_env}={override!r} but file does not exist"
                )
            return path.read_text()
    return (KNOWLEDGE_DIR / rel_path).read_text()


# --- Onboarding block ---
#
# Framed wrapper around load("onboarding"). Exposed separately because the
# indexer wants the framed block (with the "## Onboarding ... ---" header),
# not the raw file content.


_onboarding_block: str | None = None
_onboarding_source: str | None = None


def _resolve_onboarding_block() -> None:
    global _onboarding_block, _onboarding_source
    if _onboarding_block is not None:
        return

    _, override_env = _KNOWLEDGE_MAP["onboarding"]
    override = os.getenv(override_env) if override_env else None
    source = f"override: {override}" if override else "default: onboarding.md"

    content = load("onboarding").strip()
    if content:
        _onboarding_block = f"## Onboarding\n\n{content}\n\n---\n\n"
        _onboarding_source = source
    else:
        _onboarding_block = ""
        _onboarding_source = f"{source} (empty)"


def load_onboarding_block() -> str:
    """Return the onboarding block for prompt injection, or '' if empty."""
    _resolve_onboarding_block()
    return _onboarding_block or ""


def onboarding_summary() -> tuple[str, int]:
    """Return (source_label, char_count) for startup logging."""
    _resolve_onboarding_block()
    return _onboarding_source or "", len(_onboarding_block or "")


# --- Per-expert relevancy guidance ---


def load_relevancy_guidance(expert_name: str) -> str | None:
    """Load an expert's knowledge/relevancy.md. Returns None if absent.

    The triage agent loads this per-record to get source-specific cues
    about what looks like noise vs signal for that particular expert.
    """
    from pearscarf.registry import get_registry

    expert = get_registry().get_by_name(expert_name)
    if expert is None:
        return None
    path = expert.knowledge_dir / "relevancy.md"
    return path.read_text() if path.is_file() else None
