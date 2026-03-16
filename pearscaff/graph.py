"""Knowledge graph CRUD — entities, edges, facts.

The Indexer writes to the graph. The worker and other agents read from it.
Currently stubbed — extraction pipeline is being rebuilt. Only list_entity_types() is functional.
"""

from __future__ import annotations

from pearscaff.db import _get_conn, init_db


# --- Entity types ---


def list_entity_types() -> list[dict]:
    """Return all registered entity types."""
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, description, extract_fields, added_at FROM entity_types"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            # JSONB auto-deserializes; ensure list
            d["extract_fields"] = d["extract_fields"] if d["extract_fields"] else []
            result.append(d)
        return result


# --- Entities ---


def find_entity(
    entity_type: str, name: str, metadata_match: str | None = None
) -> dict | None:
    """Find an existing entity by exact name or metadata match. (stubbed)"""
    return None


def create_entity(entity_type: str, name: str, metadata: dict | None = None) -> str:
    """Create a new entity. Returns the entity ID. (stubbed)"""
    return ""


def get_entity(entity_id: str) -> dict | None:
    """Look up an entity by ID. (stubbed)"""
    return None


def search_entities(
    query: str,
    entity_type: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Search entities by name or metadata content. (stubbed)"""
    return []


# --- Edges ---


def create_edge(
    from_entity: str,
    to_entity: str,
    relationship: str,
    source_record: str,
) -> str:
    """Create a graph edge. Returns the edge ID. (stubbed)"""
    return ""


# --- Facts ---


def upsert_fact(
    entity_id: str,
    attribute: str,
    value: str,
    source_record: str,
) -> str:
    """Insert or update a fact. Returns the fact ID. (stubbed)"""
    return ""


def get_entity_facts(entity_id: str) -> list[dict]:
    """Get all facts for an entity. (stubbed)"""
    return []


def traverse_graph(entity_id: str, max_depth: int = 3) -> dict:
    """Walk edges from an entity up to max_depth hops. (stubbed)"""
    return {"entities": [], "edges": [], "source_records": []}
