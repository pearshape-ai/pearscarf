"""Knowledge module — static prompt loader.

* `load(name)` — read a single named prompt from pearscarf/knowledge/.
  Used by agents for their own system prompts (worker, curator, etc.).

Extraction prompt composition lives in `pearscarf.indexing.registry` —
it owns Layer 1 (`core_prompt`), Layer 2 (`schema_fragment`), and the
per-record `compose_prompt(record)` that joins them with Layer 3.
"""

from __future__ import annotations

from pathlib import Path


KNOWLEDGE_DIR = Path(__file__).parent


# --- Static prompt loader ---


# prompt name → relative path under pearscarf/knowledge/
_KNOWLEDGE_MAP: dict[str, str] = {
    "worker": "worker/agent.md",
    "retriever": "retriever/agent.md",
    "ingest": "ingest/agent.md",
    "ingest_extraction": "ingest/extraction.md",
    "entity_resolution": "entity_resolution/resolution.md",
    "extraction_agent": "indexer/extraction_agent.md",
    "seed_guidance": "ingest/seed_guidance.md",
    "curator_affiliated": "curator/affiliated.md",
    "curator_asserted": "curator/asserted.md",
    "gmail_mcp": "gmail/agent.md",
    "linear": "linear/agent.md",
}


def load(name: str) -> str:
    """Load a prompt by name. Returns the file content as a string."""
    return (KNOWLEDGE_DIR / _KNOWLEDGE_MAP[name]).read_text()
