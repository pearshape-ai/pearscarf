"""Retriever expert agent — searches the knowledge graph and vector store for context.

The worker delegates context queries here. Entity search, facts lookup, and
graph traversal query Neo4j. Vector search queries Qdrant.
"""

from __future__ import annotations

from typing import Any

from pearscaff import graph, vectorstore
from pearscaff.agents.expert import ExpertAgent
from pearscaff.bus import MessageBus
from pearscaff.prompts import load as load_prompt
from pearscaff.tools import BaseTool, ToolRegistry

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class SearchEntitiesTool(BaseTool):
    """Search the knowledge graph for entities by name, email, or domain."""

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
        results = graph.search_entities(query, entity_type=entity_type, limit=5)
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
    """Look up all known facts for an entity."""

    name = "facts_lookup"
    description = (
        "Get stored facts for a known entity. By default shows only current facts. "
        "Set include_superseded=true to see full history with temporal markers."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "Entity ID, e.g. 'person_001' or 'company_001'",
            },
            "include_superseded": {
                "type": "boolean",
                "description": "Include superseded (historical) facts. Default false.",
            },
        },
        "required": ["entity_id"],
    }

    def execute(self, **kwargs: Any) -> str:
        entity_id = kwargs["entity_id"]
        include_superseded = kwargs.get("include_superseded", False)
        facts = graph.get_entity_facts(entity_id, current_only=not include_superseded)
        if not facts:
            return "No facts found for this entity."
        lines = []
        for f in facts:
            conf = f" [{f['confidence']}]" if f.get("confidence") else ""
            src = f" (from: {f['source_record']})" if f.get("source_record") else ""
            temporal = ""
            if f.get("invalid_at"):
                temporal = f" [was: {f['valid_at']} -> {f['invalid_at']}]"
            elif f.get("valid_at"):
                temporal = f" [since: {f['valid_at']}]"
            lines.append(f"- {f['claim']}{conf}{src}{temporal}")
        return "\n".join(lines)


class GraphTraverseTool(BaseTool):
    """Traverse the knowledge graph from an entity to find connections."""

    name = "graph_traverse"
    description = (
        "Walk the knowledge graph from an entity to find connected entities, "
        "relationships, and source records. Traverses up to max_depth hops. "
        "By default only current (non-invalidated) relationships. "
        "Set include_historical=true to include past relationships."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "Starting entity ID, e.g. 'company_001'",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum hops to traverse (default 3)",
            },
            "include_historical": {
                "type": "boolean",
                "description": "Include invalidated relationships. Default false.",
            },
        },
        "required": ["entity_id"],
    }

    def execute(self, **kwargs: Any) -> str:
        entity_id = kwargs["entity_id"]
        max_depth = kwargs.get("max_depth", 3)
        include_historical = kwargs.get("include_historical", False)
        result = graph.traverse_graph(
            entity_id, max_depth=max_depth, current_only=not include_historical,
        )
        if not result["entities"] and not result["edges"]:
            return "No connections found."
        lines = []
        if result["entities"]:
            lines.append("Connected entities:")
            for e in result["entities"]:
                lines.append(f"  - {e['name']} ({e['type']}, id={e['id']})")
        if result["edges"]:
            lines.append("Relationships:")
            for edge in result["edges"]:
                temporal = ""
                if edge.get("invalid_at"):
                    temporal = f" [was: {edge['valid_at']} -> {edge['invalid_at']}]"
                elif edge.get("valid_at"):
                    temporal = f" [since: {edge['valid_at']}]"
                lines.append(
                    f"  - [{edge['relationship']}] {edge['from']} -> {edge['to']}{temporal}"
                )
        if result["source_records"]:
            lines.append(f"Source records: {', '.join(result['source_records'])}")
        return "\n".join(lines)


class VectorSearchTool(BaseTool):
    """Semantic similarity search across stored records."""

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
        results = vectorstore.query(query, n_results=n_results)
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


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_retriever_for_runner(
    bus: MessageBus,
) -> callable:
    """Create a factory function for the AgentRunner.

    Returns agent_factory: Callable[[session_id], ExpertAgent].
    """

    def factory(session_id: str) -> ExpertAgent:
        registry = ToolRegistry()
        registry.register(SearchEntitiesTool())
        registry.register(FactsLookupTool())
        registry.register(GraphTraverseTool())
        registry.register(VectorSearchTool())

        return ExpertAgent(
            domain="retriever",
            domain_prompt=load_prompt("retriever"),
            tool_registry=registry,
            bus=bus,
            agent_name="retriever",
        )

    return factory
