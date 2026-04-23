"""Graph query tools — read-only, Assistant-facing.

These tools give the Assistant rich read access to the knowledge graph +
vector store when responding to human queries. They wrap
`pearscarf.query.context_query` — the same read layer that the MCP
server exposes to external clients.

Distinct from `graph_access_tools.py`: those four tools are used by
Extraction and Triage during their per-record LLM turn and return terse
JSON for downstream parsing. The five tools here return formatted prose
suitable for the Assistant to summarize back to a human.
"""

from __future__ import annotations

from typing import Any

from pearscarf.query import context_query
from pearscarf.tools import BaseTool


class SearchEntitiesTool(BaseTool):
    name = "search_entities"
    description = (
        "Search the knowledge graph for entities by name, email, or domain. "
        "Use this first to check if the query references known people or companies."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Name, email address, or domain to search for",
            },
            "entity_type": {
                "type": "string",
                "description": "Optional filter: 'person' or 'company'",
            },
        },
        "required": ["query"],
    }

    def execute(self, **kwargs: Any) -> str:
        query = kwargs["query"]
        entity_type = kwargs.get("entity_type")
        results = context_query.find_entity(query, entity_type=entity_type)
        if not results:
            return "No entities found."
        lines = []
        for e in results:
            meta = e.get("metadata", {})
            meta_str = ", ".join(f"{k}={v}" for k, v in meta.items()) if meta else ""
            line = f"- {e['name']} ({e['type']}, id={e['id']})"
            if meta_str:
                line += f"  [{meta_str}]"
            lines.append(line)
        return "\n".join(lines)


class FactsLookupTool(BaseTool):
    name = "facts_lookup"
    description = (
        "Get stored facts for a known entity. Returns fact-edges grouped by edge label. "
        "By default shows only current (non-stale) facts. "
        "Set include_stale=true to see full history with temporal markers."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "Entity element ID from search_entities results",
            },
            "include_stale": {
                "type": "boolean",
                "description": "Include stale (superseded) facts. Default false.",
            },
        },
        "required": ["entity_id"],
    }

    def execute(self, **kwargs: Any) -> str:
        entity_id = kwargs["entity_id"]
        include_stale = kwargs.get("include_stale", False)
        facts = context_query.get_facts(entity_id, include_stale=include_stale)
        if not facts:
            return "No facts found for this entity."

        by_label: dict[str, list] = {}
        for f in facts:
            by_label.setdefault(f["edge_label"], []).append(f)

        lines = []
        for label, label_facts in sorted(by_label.items()):
            lines.append(f"{label}:")
            for f in label_facts:
                ft = f" ({f['fact_type']})" if f.get("fact_type") else ""
                other = f" → {f['other_name']}" if f.get("other_name") else ""
                temporal = ""
                if f.get("stale"):
                    temporal = " [stale]"
                elif f.get("source_at"):
                    temporal = f" [since: {f['source_at']}]"
                conf = f" [{f['confidence']}]" if f.get("confidence") else ""
                lines.append(f"  - {f['fact']}{ft}{other}{conf}{temporal}")
        return "\n".join(lines)


class GraphTraverseTool(BaseTool):
    name = "graph_traverse"
    description = (
        "Walk fact-edges from an entity to find connected entities and Day nodes. "
        "Traverses up to max_depth hops. Returns edge labels, fact text, and connected nodes. "
        "By default only current (non-stale) edges. "
        "Set include_stale=true to include superseded connections."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "Starting entity element ID",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum hops to traverse (default 2)",
            },
            "include_stale": {
                "type": "boolean",
                "description": "Include stale (superseded) edges. Default false.",
            },
            "edge_labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional: only traverse these edge labels (e.g. ['AFFILIATED', 'ASSERTED'])",
            },
        },
        "required": ["entity_id"],
    }

    def execute(self, **kwargs: Any) -> str:
        entity_id = kwargs["entity_id"]
        max_depth = kwargs.get("max_depth", 2)
        include_stale = kwargs.get("include_stale", False)
        edge_labels = kwargs.get("edge_labels")
        result = context_query.get_connections(
            entity_id,
            max_depth=max_depth,
            include_stale=include_stale,
            edge_labels=edge_labels,
        )
        if not result["nodes"] and not result["edges"]:
            return "No connections found."
        lines = []
        if result["nodes"]:
            lines.append("Connected nodes:")
            for n in result["nodes"]:
                if n["type"] == "day":
                    lines.append(f"  - [Day] {n['name']}")
                else:
                    lines.append(f"  - {n['name']} ({n['type']}, id={n['id']})")
        if result["edges"]:
            lines.append("Fact-edges:")
            for edge in result["edges"]:
                temporal = ""
                if edge.get("stale"):
                    temporal = " [stale]"
                elif edge.get("source_at"):
                    temporal = f" [since: {edge['source_at']}]"
                ft = f"/{edge['fact_type']}" if edge.get("fact_type") else ""
                lines.append(
                    f"  - [{edge['edge_label']}{ft}] {edge['fact']}{temporal}"
                )
        if result["source_records"]:
            lines.append(f"Source records: {', '.join(result['source_records'])}")
        return "\n".join(lines)


class DayLookupTool(BaseTool):
    name = "day_lookup"
    description = (
        "Get all single-entity facts anchored to a specific Day node. "
        "Use for 'what happened on date X' queries. "
        "Note: only returns facts explicitly anchored to the Day, not two-entity facts "
        "that happened on that date."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "date": {
                "type": "string",
                "description": "ISO date string, e.g. '2026-03-21'",
            },
        },
        "required": ["date"],
    }

    def execute(self, **kwargs: Any) -> str:
        date_str = kwargs["date"]
        facts = context_query.get_facts_for_day(date_str)
        if not facts:
            return f"No facts found for {date_str}."
        lines = [f"Facts for {date_str}:"]
        for f in facts:
            conf = f" [{f['confidence']}]" if f.get("confidence") else ""
            ft = f"/{f['fact_type']}" if f.get("fact_type") else ""
            lines.append(
                f"  - [{f['edge_label']}{ft}] {f['entity_name']} ({f['entity_type']}): {f['fact']}{conf}"
            )
        return "\n".join(lines)


class VectorSearchTool(BaseTool):
    name = "vector_search"
    description = (
        "Search for records semantically similar to the query text. "
        "Use this to find relevant emails or records that may not be in the graph."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query text",
            },
            "n_results": {
                "type": "integer",
                "description": "Number of results to return (default 5)",
            },
        },
        "required": ["query"],
    }

    def execute(self, **kwargs: Any) -> str:
        query = kwargs["query"]
        n_results = kwargs.get("n_results", 5)
        results = context_query.vector_search(query, n_results=n_results)
        if not results:
            return "No results found."
        lines = []
        for r in results:
            meta = r.get("metadata", {})
            sender = meta.get("sender", "")
            subject = meta.get("subject", "")
            header = f" — {sender}: {subject}" if sender or subject else ""
            snippet = r.get("content", "")[:200]
            lines.append(f"- [{r['id']}]{header} (score: {r['score']:.3f})\n  {snippet}")
        return "\n".join(lines)
