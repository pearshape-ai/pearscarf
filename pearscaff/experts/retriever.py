"""Retriever expert agent — searches the knowledge graph and vector store for context.

The worker delegates context queries here. Tools are currently stubbed —
extraction pipeline is being rebuilt.
"""

from __future__ import annotations

from typing import Any

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
        return "No results (extraction not yet implemented)"


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
        return "No facts (extraction not yet implemented)"


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
        return "No connections (extraction not yet implemented)"


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
        return "No results (extraction not yet implemented)"


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
