"""Retriever expert agent — searches the memory layer for context.

The worker delegates context queries here. The Retriever searches the
configured memory backend and assembles a context package.
"""

from __future__ import annotations

import json
from typing import Any

from pearscaff import graph, vectorstore
from pearscaff.agents.expert import ExpertAgent
from pearscaff.bus import MessageBus
from pearscaff.config import MEMORY_BACKEND
from pearscaff.memory import MemoryBackend, get_memory_backend
from pearscaff.tools import BaseTool, ToolRegistry

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

RETRIEVER_SYSTEM_PROMPT_SQLITE = """\
You are the retriever expert agent. You find relevant context from the knowledge \
graph and vector store.

When you receive a query:
1. Use search_entities to identify if the query references known entities (people, companies).
2. If entities found, use facts_lookup to get their attributes (email, role, etc.).
3. Use graph_traverse to find connected entities and source records (up to 3 hops).
4. Use vector_search for semantically similar records that may not be in the graph.
5. Assemble the results and reply with a structured summary.

Your reply should include:
- Facts found (entity, attribute, value)
- Related records (record IDs, type, brief summary, how found: graph or vector)
- Connected entities (name, type, relationship)
- Brief reasoning about what was found and relevance

IMPORTANT: You MUST use the reply tool to send your results back. \
Your text responses are only logged internally — nobody sees them unless you use reply.
Use reply exactly once per request. After replying, your work is done.
"""

RETRIEVER_SYSTEM_PROMPT_MEM0 = """\
You are the retriever expert agent. You find relevant context from the memory layer.

When you receive a query:
1. Use memory_search to find relevant memories, entities, and relationships.
2. Assemble the results and reply with a structured summary.

Your reply should include:
- Memories found (factual statements about people, companies, projects, finances)
- Related entities and their relationships
- Brief reasoning about what was found and relevance

IMPORTANT: You MUST use the reply tool to send your results back. \
Your text responses are only logged internally — nobody sees them unless you use reply.
Use reply exactly once per request. After replying, your work is done.
"""

# ---------------------------------------------------------------------------
# Mem0 tool
# ---------------------------------------------------------------------------


class MemorySearchTool(BaseTool):
    """Unified memory search — queries Mem0 for memories and graph connections."""

    name = "memory_search"
    description = (
        "Search the memory layer for context about a topic, person, company, "
        "project, or any other entity. Returns relevant memories and connections."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to search for",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 10)",
            },
        },
        "required": ["query"],
    }

    def __init__(self, memory: MemoryBackend) -> None:
        self._memory = memory

    def execute(self, **kwargs: Any) -> str:
        results = self._memory.search(
            query=kwargs["query"],
            limit=kwargs.get("limit", 10),
        )
        if not results:
            return f"No memories found matching '{kwargs['query']}'."
        lines = []
        for i, r in enumerate(results, 1):
            if isinstance(r, dict):
                memory = r.get("memory", r.get("text", r.get("content", str(r))))
                score = r.get("score", r.get("distance", ""))
                score_str = f" (score: {score:.3f})" if isinstance(score, float) else ""
                lines.append(f"{i}. {memory}{score_str}")
            else:
                lines.append(f"{i}. {r}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# SQLite tools (unchanged from original)
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
        results = graph.search_entities(
            query=kwargs["query"],
            entity_type=kwargs.get("entity_type"),
        )
        if not results:
            return f"No entities found matching '{kwargs['query']}'."
        lines = []
        for ent in results:
            meta = json.dumps(ent["metadata"]) if ent["metadata"] else "{}"
            lines.append(f"{ent['id']} ({ent['type']}): {ent['name']} metadata={meta}")
        return "\n".join(lines)


class FactsLookupTool(BaseTool):
    """Look up all known facts for an entity."""

    name = "facts_lookup"
    description = (
        "Get all stored facts (attributes and values) for a known entity. "
        "Use after identifying an entity with search_entities."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "Entity ID, e.g. 'person_001' or 'company_001'",
            },
        },
        "required": ["entity_id"],
    }

    def execute(self, **kwargs: Any) -> str:
        facts = graph.get_entity_facts(kwargs["entity_id"])
        if not facts:
            return f"No facts found for entity '{kwargs['entity_id']}'."
        lines = []
        for f in facts:
            lines.append(
                f"{f['attribute']}: {f['value']} (source: {f['source_record']}, "
                f"updated: {f['updated_at']})"
            )
        return "\n".join(lines)


class GraphTraverseTool(BaseTool):
    """Traverse the knowledge graph from an entity to find connections."""

    name = "graph_traverse"
    description = (
        "Walk the knowledge graph from an entity to find connected entities, "
        "relationships, and source records. Traverses up to max_depth hops."
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
        },
        "required": ["entity_id"],
    }

    def execute(self, **kwargs: Any) -> str:
        result = graph.traverse_graph(
            entity_id=kwargs["entity_id"],
            max_depth=kwargs.get("max_depth", 3),
        )

        parts = []

        if result["entities"]:
            parts.append("Connected entities:")
            for ent in result["entities"]:
                meta = json.dumps(ent["metadata"]) if ent["metadata"] else ""
                parts.append(f"  {ent['id']} ({ent['type']}): {ent['name']}" + (f" {meta}" if meta else ""))

        if result["edges"]:
            parts.append("Relationships:")
            for edge in result["edges"]:
                parts.append(
                    f"  --{edge['relationship']}--> {edge['to_entity']} "
                    f"(source: {edge['source_record']}, depth: {edge['depth']})"
                )

        if result["source_records"]:
            parts.append(f"Source records: {', '.join(result['source_records'])}")

        if not parts:
            return f"No connections found from entity '{kwargs['entity_id']}'."
        return "\n".join(parts)


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
        results = vectorstore.query(
            query_text=kwargs["query"],
            n_results=kwargs.get("n_results", 5),
        )
        if not results:
            return f"No records found matching '{kwargs['query']}'."
        lines = []
        for r in results:
            subject = r["metadata"].get("subject", "")
            sender = r["metadata"].get("sender", "")
            snippet = r["content"][:150] if r["content"] else ""
            lines.append(
                f"{r['id']} (dist={r['distance']:.3f}): "
                + (f"'{subject}' from {sender}" if subject else snippet)
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_retriever_for_runner(
    bus: MessageBus,
) -> callable:
    """Create a factory function for the AgentRunner.

    Returns agent_factory: Callable[[session_id], ExpertAgent].
    Registers Mem0 or SQLite tools based on MEMORY_BACKEND config.
    """
    memory = get_memory_backend()

    def factory(session_id: str) -> ExpertAgent:
        registry = ToolRegistry()

        if MEMORY_BACKEND == "mem0":
            registry.register(MemorySearchTool(memory))
            system_prompt = RETRIEVER_SYSTEM_PROMPT_MEM0
        else:
            registry.register(SearchEntitiesTool())
            registry.register(FactsLookupTool())
            registry.register(GraphTraverseTool())
            registry.register(VectorSearchTool())
            system_prompt = RETRIEVER_SYSTEM_PROMPT_SQLITE

        return ExpertAgent(
            domain="retriever",
            domain_prompt=system_prompt,
            tool_registry=registry,
            bus=bus,
            agent_name="retriever",
        )

    return factory
