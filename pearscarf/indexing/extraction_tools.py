"""Read-only graph tools for the extraction agent.

These tools give the agent access to the knowledge graph during
extraction. All are read-only — writes happen after validation.
"""

from __future__ import annotations

import json
from typing import Any

from pearscarf.storage import graph
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


class SaveExtractionTool(BaseTool):
    name = "save_extraction"
    description = (
        "Save the final extraction result. Call this once at the end "
        "after you have identified all entities and extracted all facts. "
        "Every fact text MUST be cut directly from the record — never paraphrase."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Entity name as it appears in the record"},
                        "type": {"type": "string", "description": "person, company, project, event"},
                        "metadata": {"type": "object", "description": "email, domain, role if known"},
                        "resolved_to": {"type": "string", "description": "Node ID if matched to existing entity, or 'new' if new entity"},
                        "canonical_name": {"type": "string", "description": "The canonical name of the matched entity, if resolved"},
                    },
                    "required": ["name", "type", "resolved_to"],
                },
            },
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "edge_label": {"type": "string", "description": "AFFILIATED, ASSERTED, or TRANSITIONED"},
                        "fact_type": {"type": "string"},
                        "fact": {"type": "string", "description": "Text cut directly from the record — never paraphrase"},
                        "from_entity": {"type": "string", "description": "Name of the from entity"},
                        "to_entity": {"type": "string", "description": "Name of the to entity, or null"},
                        "confidence": {"type": "string", "description": "stated or inferred"},
                        "valid_until": {"type": "string", "description": "ISO date if a deadline is stated, or null"},
                    },
                    "required": ["edge_label", "fact_type", "fact", "from_entity", "confidence"],
                },
            },
        },
        "required": ["entities", "facts"],
    }

    def __init__(self) -> None:
        self._result: dict | None = None

    def execute(self, **kwargs: Any) -> str:
        self._result = {
            "entities": kwargs.get("entities", []),
            "facts": kwargs.get("facts", []),
        }
        return "Extraction saved."

    @property
    def result(self) -> dict | None:
        return self._result
