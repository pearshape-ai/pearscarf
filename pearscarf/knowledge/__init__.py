"""Knowledge module — static prompts (read) and runtime stores (write).

Two distinct surfaces share this directory:

* `load(name)` — read the layered system prompts under pearscarf/knowledge/.
  Temporary shim during the prompts → knowledge migration. Most prompt
  names map 1:1 to a markdown file; the historical "extraction" prompt is
  stitched at load time from core/extraction.md, core/facts.md,
  core/output_format.md, and core/entities/*.md. This loader will be
  replaced by compose_prompt(record) in a follow-up that composes per
  record using both core layers and source-specific knowledge.

* `KnowledgeStore(domain)` — runtime write surface used by ExpertAgent to
  save knowledge collected from conversations into pearscarf/knowledge/{domain}/.
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
    "gmail_browser": "gmail/browser.md",
    "linear": "linear/agent.md",
}


def _load_extraction() -> str:
    """Stitch the layered extraction prompt: core + entities + facts + output."""
    core = KNOWLEDGE_DIR / "core"
    parts: list[str] = [(core / "extraction.md").read_text()]

    parts.append("## Entity Types\n")
    for entity_file in sorted((core / "entities").glob("*.md")):
        parts.append(entity_file.read_text())

    parts.append("## Fact Edge Labels\n")
    parts.append((core / "facts.md").read_text())

    parts.append((core / "output_format.md").read_text())

    return "\n".join(parts)


def load(name: str) -> str:
    """Load a prompt by name. Returns the file content as a string."""
    if name == "extraction":
        return _load_extraction()
    return (KNOWLEDGE_DIR / _KNOWLEDGE_MAP[name]).read_text()


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
