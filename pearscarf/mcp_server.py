"""MCP server — exposes PearScarf context queries via FastMCP over HTTP/SSE."""

from __future__ import annotations

import threading

from fastmcp import FastMCP

from pearscarf import context_query
from pearscarf.config import MCP_HOST, MCP_PORT
from pearscarf.db import init_db


mcp = FastMCP("PearScarf")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    """Health check — no auth required."""
    from starlette.responses import JSONResponse
    from pearscarf import __version__
    return JSONResponse({"status": "ok", "version": __version__})


# ---------------------------------------------------------------------------
# Entity resolution helper
# ---------------------------------------------------------------------------


def _resolve_entity(entity_name: str) -> tuple[dict | None, dict | None]:
    """Resolve a name to an entity. Returns (entity_dict, error_dict)."""
    matches = context_query.find_entity(entity_name)
    if not matches:
        return None, {"error": "not_found", "name": entity_name}
    return matches[0], None


# ---------------------------------------------------------------------------
# Primitive tools
# ---------------------------------------------------------------------------


@mcp.tool(description=(
    "Resolve a name to a canonical entity in the PearScarf graph. "
    "Use this first when you have a name and need to confirm PearScarf knows this entity, "
    "or when a name could match multiple entities."
))
def find_entity(name: str, entity_type: str = None) -> dict:
    """Search for entities by name."""
    results = context_query.find_entity(name, entity_type)
    if not results:
        return {"error": "not_found", "name": name}
    return {"entities": results}


@mcp.tool(description=(
    "Get facts about an entity. The workhorse query — returns all known facts, "
    "optionally filtered by edge label (AFFILIATED/ASSERTED/TRANSITIONED), "
    "fact type (employee, commitment, status_change, etc.), or time range. "
    "Use for current state, commitments, blockers, affiliations."
))
def get_facts(
    entity_name: str,
    edge_label: str = None,
    fact_type: str = None,
    include_stale: bool = False,
    since: str = None,
) -> dict:
    """Get fact-edges for an entity with optional filters."""
    entity, err = _resolve_entity(entity_name)
    if err:
        return err
    facts = context_query.get_facts(
        entity["id"],
        edge_label=edge_label,
        fact_type=fact_type,
        include_stale=include_stale,
        since=since,
    )
    return {
        "entity": {"id": entity["id"], "name": entity["name"], "type": entity["type"]},
        "facts": facts,
        "count": len(facts),
    }


@mcp.tool(description=(
    "Get entities directly connected to this entity via fact-edges. "
    "Returns connected people, companies, projects — not Day nodes. "
    "Use to understand who/what an entity is connected to."
))
def get_connections(
    entity_name: str,
    edge_label: str = None,
    include_stale: bool = False,
) -> dict:
    """Get connected entities via 1-hop traversal."""
    entity, err = _resolve_entity(entity_name)
    if err:
        return err
    edge_labels = [edge_label] if edge_label else None
    result = context_query.get_connections(
        entity["id"],
        max_depth=1,
        include_stale=include_stale,
        edge_labels=edge_labels,
    )
    # Filter out Day nodes from connections
    connections = [n for n in result.get("nodes", []) if n.get("type") != "day"]
    return {
        "entity": {"id": entity["id"], "name": entity["name"], "type": entity["type"]},
        "connections": connections,
        "edges": result.get("edges", []),
        "count": len(connections),
    }


class MCPServer:
    """Background thread running the FastMCP server."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        init_db()
        mcp.run(
            transport="sse",
            host=MCP_HOST,
            port=MCP_PORT,
        )

    def start(self) -> None:
        """Start MCP server in a background daemon thread."""
        self._thread = threading.Thread(
            target=self._run, name="mcp-server", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        # FastMCP doesn't expose a clean shutdown — daemon thread dies with process
        pass

    def run_foreground(self) -> None:
        """Run MCP server in the foreground (blocking)."""
        init_db()
        print(f"MCP server starting on {MCP_HOST}:{MCP_PORT}")
        mcp.run(
            transport="sse",
            host=MCP_HOST,
            port=MCP_PORT,
        )
