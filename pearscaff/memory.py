"""Pluggable memory backend — abstracts storage for the Indexer and Retriever.

MEMORY_BACKEND=mem0  → Mem0 with Neo4j graph + vector (LLM-driven extraction)
MEMORY_BACKEND=sqlite → existing SQLite facts + graph + ChromaDB pipeline
"""

from __future__ import annotations

import json
import traceback
from abc import ABC, abstractmethod
from typing import Any

import anthropic

from pearscaff import graph, log, store, vectorstore
from pearscaff.config import (
    ANTHROPIC_API_KEY,
    MEMORY_BACKEND,
    MODEL,
    NEO4J_PASSWORD,
    NEO4J_URL,
    NEO4J_USER,
)
from pearscaff.db import init_db

# ---------------------------------------------------------------------------
# Custom extraction prompt for Mem0
# ---------------------------------------------------------------------------

MEM0_EXTRACTION_PROMPT = """\
You are extracting structured memories from operational data (emails, messages, notes).

Focus on:
- People: names, email addresses, roles, titles, affiliations
- Companies/organizations: names, domains, industries
- Projects and initiatives: names, status, ownership
- Financial details: amounts, invoices, budgets, payment terms
- Commitments and deadlines: who promised what, by when
- Relationships: who works with whom, who is a client/partner/vendor of whom

Ignore:
- Greetings, sign-offs, and email signatures
- Boilerplate disclaimers and footer text
- Timestamps that are just "when the email was sent"
- Generic pleasantries with no factual content

Extract concise, factual memories. Each memory should be a standalone statement \
that would be useful when retrieved later.\
"""


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class MemoryBackend(ABC):
    """Common interface for memory backends."""

    @abstractmethod
    def add(self, content: str, metadata: dict[str, Any]) -> None:
        """Index content into the memory layer."""

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search memories. Returns list of result dicts."""


# ---------------------------------------------------------------------------
# Mem0 backend
# ---------------------------------------------------------------------------


class Mem0Backend(MemoryBackend):
    """Mem0 with Neo4j graph memory."""

    def __init__(self) -> None:
        from mem0 import Memory

        self._mem = Memory.from_config(
            {
                "graph_store": {
                    "provider": "neo4j",
                    "config": {
                        "url": NEO4J_URL,
                        "username": NEO4J_USER,
                        "password": NEO4J_PASSWORD,
                    },
                },
                "llm": {
                    "provider": "anthropic",
                    "config": {
                        "model": MODEL,
                        "api_key": ANTHROPIC_API_KEY,
                    },
                },
                "custom_prompt": MEM0_EXTRACTION_PROMPT,
            }
        )

    def add(self, content: str, metadata: dict[str, Any]) -> None:
        self._mem.add(content, user_id="default", metadata=metadata)

    def search(self, query: str, limit: int = 10) -> list[dict]:
        results = self._mem.search(query, user_id="default", limit=limit)
        # Normalize to list of dicts with 'memory', 'score', 'metadata' keys
        out = []
        for r in results.get("results", results) if isinstance(results, dict) else results:
            if isinstance(r, dict):
                out.append(r)
            else:
                out.append({"memory": str(r)})
        return out


# ---------------------------------------------------------------------------
# SQLite fallback — wraps existing graph.py + vectorstore.py + indexer logic
# ---------------------------------------------------------------------------

EXTRACTION_TEMPLATE = """\
Given this {record_type} record, extract all entities, relationships, and facts.
Respond in JSON only, no other text.

Entity types to extract:
{entity_types_block}

Record ({record_id}):
{content}

Respond with exactly this JSON structure:
{{
  "entities": [
    {{"type": "person", "name": "Full Name", "metadata": {{"email": "...", "role": "..."}}}}
  ],
  "relationships": [
    {{"from": "Entity Name", "to": "Entity Name", "type": "relationship_type"}}
  ],
  "facts": [
    {{"entity": "Entity Name", "attribute": "attribute_name", "value": "value"}}
  ]
}}

If no entities, relationships, or facts can be extracted, return empty arrays.\
"""


class SqliteBackend(MemoryBackend):
    """Original pipeline: LLM extraction → SQLite graph → ChromaDB vectors."""

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or None)

    # -- public interface --------------------------------------------------

    def add(self, content: str, metadata: dict[str, Any]) -> None:
        record_id = metadata.get("record_id", "unknown")
        record_type = metadata.get("type", "email")

        # Step 1: LLM extraction
        try:
            result = self._extract(record_type, record_id, content)
        except json.JSONDecodeError as exc:
            log.write("indexer", "--", "error", f"JSON parse error for {record_id}: {exc}")
            return
        except Exception as exc:
            log.write("indexer", "--", "error", f"extraction failed for {record_id}: {exc}")
            return

        entities = result.get("entities", [])
        relationships = result.get("relationships", [])
        facts = result.get("facts", [])

        log.write(
            "indexer", "--", "result",
            f"extracted {len(entities)} entities, "
            f"{len(relationships)} relationships, {len(facts)} facts",
        )

        # Step 2: Resolve entities
        name_to_id: dict[str, str] = {}
        for ent in entities:
            try:
                eid = self._resolve_entity(ent)
                name_to_id[ent["name"]] = eid
                log.write("indexer", "--", "action", f"entity '{ent['name']}' -> {eid}")
            except Exception as exc:
                log.write("indexer", "--", "error", f"entity resolve failed: {exc}")

        # Step 3: Create edges
        edges_created = 0
        for rel in relationships:
            from_id = name_to_id.get(rel.get("from"))
            to_id = name_to_id.get(rel.get("to"))
            if from_id and to_id:
                try:
                    graph.create_edge(from_id, to_id, rel["type"], record_id)
                    edges_created += 1
                except Exception as exc:
                    log.write("indexer", "--", "error", f"edge create failed: {exc}")

        # Step 4: Upsert facts
        facts_written = 0
        for fact in facts:
            entity_id = name_to_id.get(fact.get("entity"))
            if entity_id:
                try:
                    graph.upsert_fact(entity_id, fact["attribute"], fact["value"], record_id)
                    facts_written += 1
                except Exception as exc:
                    log.write("indexer", "--", "error", f"fact upsert failed: {exc}")

        log.write(
            "indexer", "--", "action",
            f"wrote {edges_created} edges, {facts_written} facts for {record_id}",
        )

        # Step 5: Embed in ChromaDB
        try:
            embed_metadata = {
                "type": record_type,
                "source": metadata.get("source", ""),
                "created_at": metadata.get("created_at", ""),
            }
            if record_type == "email":
                email = store.get_email(record_id)
                if email:
                    embed_metadata["sender"] = email.get("sender", "")
                    embed_metadata["subject"] = email.get("subject", "")
            vectorstore.add_record(record_id, content, embed_metadata)
            log.write("indexer", "--", "action", f"embedded {record_id} in ChromaDB")
        except Exception as exc:
            log.write("indexer", "--", "error", f"embedding failed for {record_id}: {exc}")

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Run all three search strategies and merge results."""
        results: list[dict] = []

        # 1. Entity search
        entities = graph.search_entities(query, limit=limit)
        for ent in entities:
            facts = graph.get_entity_facts(ent["id"])
            results.append({
                "type": "entity",
                "entity_id": ent["id"],
                "entity_name": ent["name"],
                "entity_type": ent["type"],
                "metadata": ent.get("metadata", {}),
                "facts": [
                    {"attribute": f["attribute"], "value": f["value"]}
                    for f in facts
                ],
            })

            # Traverse graph from this entity
            traversal = graph.traverse_graph(ent["id"], max_depth=2)
            for connected in traversal["entities"]:
                results.append({
                    "type": "connected_entity",
                    "entity_id": connected["id"],
                    "entity_name": connected["name"],
                    "entity_type": connected["type"],
                    "via": ent["name"],
                })

        # 2. Vector search
        vector_results = vectorstore.query(query, n_results=min(limit, 5))
        for vr in vector_results:
            results.append({
                "type": "vector_match",
                "record_id": vr["id"],
                "content": vr["content"][:300] if vr["content"] else "",
                "metadata": vr["metadata"],
                "distance": vr["distance"],
            })

        return results

    # -- private helpers ---------------------------------------------------

    def _build_entity_types_block(self) -> str:
        types = graph.list_entity_types()
        lines = []
        for et in types:
            fields = ", ".join(et["extract_fields"])
            lines.append(f"- {et['name']}: {et['description']} Fields: {fields}")
        return "\n".join(lines)

    def _extract(self, record_type: str, record_id: str, content: str) -> dict:
        entity_types_block = self._build_entity_types_block()
        prompt = EXTRACTION_TEMPLATE.format(
            record_type=record_type,
            entity_types_block=entity_types_block,
            record_id=record_id,
            content=content,
        )
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text

        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        return json.loads(text)

    def _resolve_entity(self, extracted: dict) -> str:
        entity_type = extracted["type"]
        name = extracted["name"]
        metadata = extracted.get("metadata", {})

        metadata_match = None
        if entity_type == "person" and metadata.get("email"):
            metadata_match = metadata["email"]
        elif entity_type == "company" and metadata.get("domain"):
            metadata_match = metadata["domain"]

        existing = graph.find_entity(entity_type, name, metadata_match)
        if existing:
            return existing["id"]

        return graph.create_entity(entity_type, name, metadata)


# ---------------------------------------------------------------------------
# Factory — lazy singleton
# ---------------------------------------------------------------------------

_instance: MemoryBackend | None = None


def get_memory_backend() -> MemoryBackend:
    """Return the configured memory backend (lazy singleton)."""
    global _instance
    if _instance is None:
        init_db()
        if MEMORY_BACKEND == "mem0":
            _instance = Mem0Backend()
        else:
            _instance = SqliteBackend()
    return _instance
