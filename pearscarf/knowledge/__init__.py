from __future__ import annotations

from pathlib import Path


KNOWLEDGE_DIR = Path(__file__).parent


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
