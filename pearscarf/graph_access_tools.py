"""Read-only graph access tools — shared by Triage and Extraction.

The record-side consumers (Triage, Extraction) need to read the
knowledge graph during their LLM turn: look up known entities, search
by name, check surface-form aliases, pull an entity's context. These
are read-only. The Extraction-specific write tool (`SaveExtractionTool`)
lives with the `Extraction` consumer in `pearscarf.extraction`.
"""

from __future__ import annotations

import json
from typing import Any

from pearscarf.storage import graph
from pearscarf.storage.graph import _LABELS
from pearscarf.tools import BaseTool


class FindEntityTool(BaseTool):
    name = "find_entity"
    description = (
        "Exact name match for an entity in the graph. "
        "Returns the entity with ID and metadata, or 'not found'."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "entity_type": {
                "type": "string",
                "description": "Entity type: person, company, project, event",
            },
            "name": {
                "type": "string",
                "description": "Exact entity name to search for",
            },
        },
        "required": ["entity_type", "name"],
    }

    def execute(self, **kwargs: Any) -> str:
        result = graph.find_entity(kwargs["entity_type"], kwargs["name"])
        if result:
            return json.dumps({
                "found": True,
                "id": result["id"],
                "name": result["name"],
                "type": result.get("type", kwargs["entity_type"]),
                "metadata": result.get("metadata", {}),
            })
        return json.dumps({"found": False})


class SearchEntitiesTool(BaseTool):
    name = "search_entities"
    description = (
        "Fuzzy search for entities by name substring. "
        "Use when exact match fails — searches by partial name, "
        "initials, or prefix. Returns a list of candidates."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — name, partial name, or initials",
            },
            "entity_type": {
                "type": "string",
                "description": "Entity type to filter by: person, company, project, event",
            },
        },
        "required": ["query"],
    }

    def execute(self, **kwargs: Any) -> str:
        results = graph.search_entities(
            kwargs["query"],
            entity_type=kwargs.get("entity_type"),
            limit=5,
        )
        if not results:
            return json.dumps({"found": False, "candidates": []})
        candidates = [
            {
                "id": r["id"],
                "name": r["name"],
                "type": r.get("type", ""),
                "metadata": r.get("metadata", {}),
            }
            for r in results
        ]
        return json.dumps({"found": True, "candidates": candidates})


class CheckAliasTool(BaseTool):
    name = "check_alias"
    description = (
        "Check if a surface form has been resolved before as an alias. "
        "Looks up IDENTIFIED_AS edges by exact surface form match."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "entity_type": {
                "type": "string",
                "description": "Entity type: person, company, project, event",
            },
            "surface_form": {
                "type": "string",
                "description": "The surface form to check",
            },
        },
        "required": ["entity_type", "surface_form"],
    }

    def execute(self, **kwargs: Any) -> str:
        entity_type = kwargs["entity_type"]
        surface_form = kwargs["surface_form"]
        label = {"person": "Person", "company": "Company", "project": "Project",
                 "event": "Event", "repository": "Repository"}.get(entity_type, entity_type.capitalize())

        with graph.get_session() as session:
            result = session.run(
                f"MATCH (n:{label})-[r:IDENTIFIED_AS]->(n) "
                "WHERE toLower(r.surface_form) = toLower($sf) "
                "RETURN n.name AS name, elementId(n) AS eid "
                "LIMIT 1",
                sf=surface_form,
            )
            record = result.single()
            if record:
                return json.dumps({
                    "found": True,
                    "id": record["eid"],
                    "name": record["name"],
                    "type": entity_type,
                })
        return json.dumps({"found": False})


class GetEntityContextTool(BaseTool):
    name = "get_entity_context"
    description = (
        "Get facts and connections for an entity. Use this to verify "
        "a candidate match — check if the candidate's context aligns "
        "with what you see in the record."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "The entity's node ID from a previous find/search result",
            },
        },
        "required": ["entity_id"],
    }

    def execute(self, **kwargs: Any) -> str:
        ctx = graph.get_entity_context(kwargs["entity_id"])
        entity = ctx.get("entity", {})
        facts = ctx.get("facts", [])
        connections = ctx.get("connections", [])

        parts = [f"Entity: {entity.get('name', '')} ({entity.get('type', '')})"]
        if facts:
            parts.append("Facts:")
            for f in facts[:10]:
                parts.append(f"  [{f.get('edge_label', '')}] {f.get('fact', '')}")
        if connections:
            parts.append("Connections:")
            for c in connections[:10]:
                parts.append(f"  {c.get('name', '')} ({c.get('type', '')})")
        return "\n".join(parts)


def _strip_node_props(node: Any) -> dict:
    return {k: v for k, v in dict(node).items() if k not in ("name", "created_at")}


def _identifier_hit(entity_type: str, identifier: str) -> dict | None:
    """Exact email (person) or domain (company). One unique hit or None."""
    prop = {"person": "email", "company": "domain"}.get(entity_type)
    if prop is None:
        return None
    label = _LABELS.get(entity_type, entity_type.capitalize())
    with graph.get_session() as session:
        result = session.run(
            f"MATCH (n:{label}) WHERE toLower(n.{prop}) = toLower($v) "
            "RETURN n, elementId(n) AS eid LIMIT 1",
            v=identifier,
        )
        record = result.single()
        if not record:
            return None
        node = record["n"]
        return {
            "id": record["eid"],
            "name": node.get("name", ""),
            "type": entity_type,
            "metadata": _strip_node_props(node),
        }


def _exact_name_hits(entity_type: str, name: str, limit: int = 5) -> list[dict]:
    """All exact-name matches (case-insensitive). Empty / single / many handled by caller."""
    label = _LABELS.get(entity_type, entity_type.capitalize())
    with graph.get_session() as session:
        result = session.run(
            f"MATCH (n:{label}) WHERE toLower(n.name) = toLower($name) "
            "RETURN n, elementId(n) AS eid LIMIT $limit",
            name=name, limit=limit,
        )
        hits = []
        for record in result:
            node = record["n"]
            hits.append({
                "id": record["eid"],
                "name": node.get("name", ""),
                "type": entity_type,
                "metadata": _strip_node_props(node),
            })
        return hits


def _alias_hits(entity_type: str, surface_form: str, limit: int = 5) -> list[dict]:
    """All entities with an IDENTIFIED_AS self-loop carrying this surface form."""
    label = _LABELS.get(entity_type, entity_type.capitalize())
    with graph.get_session() as session:
        result = session.run(
            f"MATCH (n:{label})-[r:IDENTIFIED_AS]->(n) "
            "WHERE toLower(r.surface_form) = toLower($sf) "
            "RETURN n, elementId(n) AS eid LIMIT $limit",
            sf=surface_form, limit=limit,
        )
        hits = []
        for record in result:
            node = record["n"]
            hits.append({
                "id": record["eid"],
                "name": node.get("name", ""),
                "type": entity_type,
                "metadata": _strip_node_props(node),
            })
        return hits


def _brief_context(entity_id: str) -> dict:
    """Compact context — top 3 facts + top 3 connections."""
    ctx = graph.get_entity_context(entity_id, max_facts=3, max_connections=3)
    return {
        "facts": [
            f"[{f.get('edge_label', '')}] {f.get('fact', '')}"
            for f in ctx.get("facts", [])
        ],
        "connections": [
            f"{c.get('name', '')} ({c.get('type', '')})"
            for c in ctx.get("connections", [])
        ],
    }


class ResolveEntityTool(BaseTool):
    """Consolidated entity resolver — runs exact/alias/fuzzy lookups in one call.

    Replaces the four-step cascade (find_entity → search_entities → check_alias
    → get_entity_context) the extractor used to run per entity. Auto-fetches
    brief context for every returned match, so the agent can decide definitively
    from one tool response. Intended primary tool for Extraction.
    """

    name = "resolve_entity"
    description = (
        "Resolve a named reference to an existing graph entity, or determine no match. "
        "One call tries exact-name match (with optional email/domain identifier), "
        "alias lookup, and fuzzy fallback; returns a definitive match with context, "
        "candidates with context, or none. Use before deciding to create a new entity."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "entity_type": {
                "type": "string",
                "description": "person, company, project, or event",
            },
            "name": {
                "type": "string",
                "description": "The name / surface form as it appears in the record",
            },
            "identifier": {
                "type": "string",
                "description": (
                    "Optional strong identifier: email for persons, domain for "
                    "companies. Pass it when available; leave empty otherwise."
                ),
            },
        },
        "required": ["entity_type", "name"],
    }

    def execute(self, **kwargs: Any) -> str:
        entity_type = kwargs["entity_type"]
        name = kwargs["name"]
        identifier = kwargs.get("identifier") or None

        def _bundle(hit: dict) -> dict:
            return {"entity": hit, "context": _brief_context(hit["id"])}

        # 1. Identifier first — email/domain is stronger than name.
        if identifier:
            id_hit = _identifier_hit(entity_type, identifier)
            if id_hit:
                return json.dumps({
                    "match": "definitive",
                    "via": "identifier",
                    "entity": id_hit,
                    "context": _brief_context(id_hit["id"]),
                })

        # 2. Exact name — 0 / 1 / many, each handled differently.
        exact_hits = _exact_name_hits(entity_type, name)
        if len(exact_hits) == 1:
            h = exact_hits[0]
            return json.dumps({
                "match": "definitive",
                "via": "exact_name",
                "entity": h,
                "context": _brief_context(h["id"]),
            })
        if len(exact_hits) > 1:
            return json.dumps({
                "match": "candidates",
                "via": "exact_name_ambiguous",
                "candidates": [_bundle(h) for h in exact_hits],
            })

        # 3. Alias self-loop — also may have collisions.
        alias_hits = _alias_hits(entity_type, name)
        if len(alias_hits) == 1:
            h = alias_hits[0]
            return json.dumps({
                "match": "definitive",
                "via": "alias",
                "entity": h,
                "context": _brief_context(h["id"]),
            })
        if len(alias_hits) > 1:
            return json.dumps({
                "match": "candidates",
                "via": "alias_ambiguous",
                "candidates": [_bundle(h) for h in alias_hits],
            })

        # 4. Fuzzy fallback.
        fuzzy = graph.search_entities(name, entity_type=entity_type, limit=3)
        if fuzzy:
            return json.dumps({
                "match": "candidates",
                "via": "fuzzy_name",
                "candidates": [
                    {
                        "entity": {
                            "id": r["id"],
                            "name": r["name"],
                            "type": r.get("type", entity_type),
                            "metadata": r.get("metadata", {}),
                        },
                        "context": _brief_context(r["id"]),
                    }
                    for r in fuzzy
                ],
            })

        return json.dumps({"match": "none"})
