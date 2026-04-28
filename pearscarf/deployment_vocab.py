"""Deployment-vocabulary loader.

Reads a deployment-specific `vocab.yaml` pointed to by the
`DEPLOYMENT_VOCAB_PATH` env var. Operators use this to declare entity
types and fact_types specific to *this* deployment without forking the
framework or attaching the vocabulary to a record-source expert.

Format (`vocab.yaml`):

    entity_types:
      - name: sub_system
        description: A deployed service or component in this stack.
        section: sub_systems   # optional; defaults to f"{name}s"

    fact_types:
      AFFILIATED:
        - name: component_of
          description: A is a structural component of B.
        - name: runs_on
      TRANSITIONED:
        - name: attribute_change

When `DEPLOYMENT_VOCAB_PATH` is unset the loader returns an empty vocab
and the framework behaves exactly as before.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class EntityType:
    name: str
    description: str = ""
    section: str | None = None

    @property
    def section_name(self) -> str:
        return self.section or f"{self.name}s"


@dataclass
class FactType:
    name: str
    description: str = ""


@dataclass
class DeploymentVocab:
    entity_types: list[EntityType] = field(default_factory=list)
    fact_types: dict[str, list[FactType]] = field(default_factory=dict)


_vocab: DeploymentVocab | None = None


def get_vocab() -> DeploymentVocab:
    """Return the deployment vocab (cached after first load)."""
    global _vocab
    if _vocab is not None:
        return _vocab

    path_str = os.getenv("DEPLOYMENT_VOCAB_PATH")
    if not path_str:
        _vocab = DeploymentVocab()
        return _vocab

    path = Path(path_str)
    if not path.is_file():
        raise FileNotFoundError(f"DEPLOYMENT_VOCAB_PATH={path_str!r} but file does not exist")

    data = yaml.safe_load(path.read_text()) or {}

    entity_types = [
        EntityType(
            name=e["name"],
            description=e.get("description", ""),
            section=e.get("section"),
        )
        for e in (data.get("entity_types") or [])
    ]

    fact_types: dict[str, list[FactType]] = {}
    for label, types in (data.get("fact_types") or {}).items():
        fact_types[label] = [
            FactType(name=t["name"], description=t.get("description", "")) for t in (types or [])
        ]

    _vocab = DeploymentVocab(entity_types=entity_types, fact_types=fact_types)
    return _vocab


def reset_vocab() -> None:
    """Drop the cached vocab. Used by tests that change DEPLOYMENT_VOCAB_PATH."""
    global _vocab
    _vocab = None
