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


@mcp.tool(description=(
    "Find how two entities are connected in the PearScarf graph. "
    "Returns direct facts between them and the shortest path if no direct connection exists. "
    "Use before drafting a message or making a decision involving two parties."
))
def get_relationship(entity_a: str, entity_b: str) -> dict:
    """Find the relationship between two entities."""
    ent_a, err_a = _resolve_entity(entity_a)
    if err_a:
        return err_a
    ent_b, err_b = _resolve_entity(entity_b)
    if err_b:
        return err_b

    result = context_query.get_path(ent_a["id"], ent_b["id"])
    return {
        "entity_a": {"id": ent_a["id"], "name": ent_a["name"], "type": ent_a["type"]},
        "entity_b": {"id": ent_b["id"], "name": ent_b["name"], "type": ent_b["type"]},
        "direct_facts": result.get("direct_facts", []),
        "path": result.get("path", []),
    }


@mcp.tool(description=(
    "Find AFFILIATED facts where the graph holds two current conflicting values for the same slot. "
    "These are cases where the Curator detected equal source_at timestamps and could not resolve automatically. "
    "Use when reviewing graph health or validating entity affiliations."
))
def get_conflicts(entity_name: str = None) -> dict:
    """Find conflicting AFFILIATED facts."""
    entity_id = None
    if entity_name:
        entity, err = _resolve_entity(entity_name)
        if err:
            return err
        entity_id = entity["id"]

    conflicts = context_query.get_conflicts(entity_id=entity_id)
    return {
        "conflicts": conflicts,
        "count": len(conflicts),
    }


# ---------------------------------------------------------------------------
# Convenience tools
# ---------------------------------------------------------------------------


@mcp.tool(description=(
    "Get a full picture of an entity — all current facts and direct connections. "
    "Use this before acting on behalf of or about a person, company, or project. "
    "Returns facts in chronological order by default, or grouped by edge label with format='clustered'."
))
def get_entity_context(
    entity_name: str,
    format: str = "chronological",
    include_stale: bool = False,
) -> dict:
    """Full entity context: facts + connections."""
    if format not in ("chronological", "clustered"):
        return {"error": "invalid_format", "valid_values": ["chronological", "clustered"]}

    entity, err = _resolve_entity(entity_name)
    if err:
        return err

    facts = context_query.get_facts(entity["id"], include_stale=include_stale)
    conns_result = context_query.get_connections(
        entity["id"], max_depth=1, include_stale=include_stale
    )
    connections = [n for n in conns_result.get("nodes", []) if n.get("type") != "day"]

    entity_info = {
        "id": entity["id"],
        "name": entity["name"],
        "type": entity["type"],
        "metadata": entity.get("metadata", {}),
    }

    if format == "chronological":
        facts.sort(key=lambda f: f.get("source_at", ""))
        return {
            "entity": entity_info,
            "facts": facts,
            "connections": connections,
            "count": len(facts),
        }
    else:
        # Clustered by edge_label
        clustered: dict[str, list] = {}
        for f in facts:
            label = f.get("edge_label", "OTHER")
            clustered.setdefault(label, []).append(f)
        return {
            "entity": entity_info,
            "facts": clustered,
            "connections": connections,
            "count": len(facts),
        }


@mcp.tool(description=(
    "Get what is structurally true about an entity right now — "
    "current role, employer, project memberships. "
    "Returns AFFILIATED facts only. "
    "Use when you need to know who someone works for or what projects they belong to."
))
def get_current_state(entity_name: str) -> dict:
    """Current affiliations only."""
    entity, err = _resolve_entity(entity_name)
    if err:
        return err

    affiliations = context_query.get_facts(
        entity["id"], edge_label="AFFILIATED", include_stale=False
    )
    return {
        "entity": {"id": entity["id"], "name": entity["name"], "type": entity["type"]},
        "affiliations": affiliations,
        "count": len(affiliations),
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
