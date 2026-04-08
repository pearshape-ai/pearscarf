"""Read-only data access layer for context queries.

Single module through which both the retriever agent and the MCP server
access graph, vector, and record data. All functions are read-only.
"""

from __future__ import annotations

from pearscarf.storage import graph, vectorstore
from pearscarf.storage.store import get_communications_for_entity


def find_entity(name: str, entity_type: str | None = None) -> list[dict]:
    """Search for entities by name, email, or domain.

    Returns list of {id, name, type, metadata}.
    """
    return graph.search_entities(name, entity_type=entity_type, limit=10)


def get_facts(
    entity_id: str,
    edge_label: str | None = None,
    fact_type: str | None = None,
    include_stale: bool = False,
    since: str | None = None,
) -> list[dict]:
    """Get fact-edges for an entity with optional filters.

    Wraps graph.get_facts_for_entity with post-filtering.
    """
    facts = graph.get_facts_for_entity(entity_id, include_stale=include_stale)

    if edge_label:
        facts = [f for f in facts if f.get("edge_label") == edge_label]
    if fact_type:
        facts = [f for f in facts if f.get("fact_type") == fact_type]
    if since:
        facts = [f for f in facts if (f.get("source_at") or "") >= since]

    return facts


def get_connections(
    entity_id: str,
    max_depth: int = 1,
    include_stale: bool = False,
    edge_labels: list[str] | None = None,
) -> dict:
    """Traverse fact-edges from an entity.

    Returns {nodes, edges, source_records}.
    """
    return graph.traverse_fact_edges(
        entity_id,
        max_depth=max_depth,
        current_only=not include_stale,
        edge_labels=edge_labels,
    )


def get_facts_for_day(date: str) -> list[dict]:
    """Get all single-entity facts anchored to a Day node."""
    return graph.get_facts_for_day(date)


def get_path(entity_id_a: str, entity_id_b: str) -> dict:
    """Find the shortest path between two entities.

    Returns {path: [...], direct_facts: [...]}.
    """
    return graph.get_path(entity_id_a, entity_id_b)


def get_conflicts(entity_id: str | None = None) -> list[dict]:
    """Find AFFILIATED slots with multiple current edges.

    Returns list of conflict dicts.
    """
    return graph.get_conflicts(entity_id=entity_id)


def get_communications(entity_id: str, since: str | None = None) -> list[dict]:
    """Get emails where the entity appears as sender or recipient.

    Resolves entity_id to name/email via graph, then queries Postgres.
    """
    entity = graph.get_entity(entity_id)
    if not entity:
        return []

    # Search by name and email
    name = entity.get("name", "")
    email = entity.get("metadata", {}).get("email", "")

    results = []
    if name:
        results.extend(get_communications_for_entity(name, since=since))
    if email and email != name:
        for r in get_communications_for_entity(email, since=since):
            if r["record_id"] not in {e["record_id"] for e in results}:
                results.append(r)

    results.sort(key=lambda r: r.get("received_at", ""), reverse=True)
    return results[:20]


def vector_search(query: str, n_results: int = 5) -> list[dict]:
    """Semantic similarity search across stored records."""
    return vectorstore.query(query, n_results=n_results)
