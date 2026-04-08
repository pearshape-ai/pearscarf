"""Knowledge module — static prompts (read) and runtime stores (write).

Three surfaces share this directory:

* `load(name)` — read a single named prompt from pearscarf/knowledge/.
  Used by agents for their own system prompts (worker, curator, etc.).

* `compose_prompt(record)` — build the extraction system prompt for a
  given record. Layer 1 (core/extraction.md + facts.md + output_format.md)
  and Layer 2 (core/entities/*.md) are universal and cached after first
  use. Layer 3 ({source}/extraction.md) is appended per record based on
  source_type. Ingest records skip the layered composition entirely and
  use ingest/extraction.md as their full prompt.

* `KnowledgeStore(domain)` — runtime write surface used by ExpertAgent
  to save knowledge collected from conversations into
  pearscarf/knowledge/{domain}/.
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
    "curator_affiliated": "curator/affiliated.md",
    "curator_asserted": "curator/asserted.md",
    "gmail_mcp": "gmail/agent.md",
    "linear": "linear/agent.md",
}


def load(name: str) -> str:
    """Load a prompt by name. Returns the file content as a string."""
    return (KNOWLEDGE_DIR / _KNOWLEDGE_MAP[name]).read_text()


# --- Extraction prompt composition ---


# record_type → source folder under pearscarf/knowledge/ for Layer 3
_SOURCE_BY_RECORD_TYPE: dict[str, str] = {
    "email": "gmail",
    "issue": "linear",
    "issue_change": "linear",
}


_cached_core: str | None = None


def _build_core() -> str:
    """Assemble Layer 1 + Layer 2 once. Source-agnostic, cached for the process."""
    core = KNOWLEDGE_DIR / "core"
    parts: list[str] = [(core / "extraction.md").read_text()]

    parts.append("## Entity Types\n")
    for entity_file in sorted((core / "entities").glob("*.md")):
        parts.append(entity_file.read_text())

    parts.append("## Fact Edge Labels\n")
    parts.append((core / "facts.md").read_text())

    parts.append((core / "output_format.md").read_text())

    return "\n".join(parts)


def _core_prompt() -> str:
    """Return the cached Layer 1+2 prompt, building it on first call."""
    global _cached_core
    if _cached_core is None:
        _cached_core = _build_core()
    return _cached_core


def _layer_3(source: str) -> str:
    """Read the Layer 3 extraction guidance for a source. Empty string if missing."""
    path = KNOWLEDGE_DIR / source / "extraction.md"
    if path.exists():
        return path.read_text()
    return ""


def compose_prompt(record: dict) -> str:
    """Compose the extraction system prompt for a given record.

    Ingest records use ingest/extraction.md as a complete prompt — they do
    not participate in layered composition. Every other record gets Layer
    1+2 (cached) plus the Layer 3 guidance for its source.
    """
    record_type = record.get("type", "")

    if record_type == "ingest":
        return load("ingest_extraction")

    core = _core_prompt()
    source = _SOURCE_BY_RECORD_TYPE.get(record_type, "")
    if source:
        layer_3 = _layer_3(source)
        if layer_3:
            return f"{core}\n{layer_3}"
    return core


# --- Runtime knowledge store ---


class KnowledgeStore:
    def __init__(self, domain: str) -> None:
        self._domain = domain
        self._dir = KNOWLEDGE_DIR / domain
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, content: str) -> None:
        path = self._dir / f"{name}.md"
        path.write_text(content)

    def load_all(self) -> str:
        parts: list[str] = []
        for path in sorted(self._dir.glob("*.md")):
            parts.append(f"## {path.stem}\n\n{path.read_text()}")
        return "\n\n".join(parts)

    def list(self) -> list[str]:
        return [p.stem for p in sorted(self._dir.glob("*.md"))]

    def has_knowledge(self) -> bool:
        return any(self._dir.glob("*.md"))
