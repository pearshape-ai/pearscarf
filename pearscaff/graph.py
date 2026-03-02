"""Knowledge graph CRUD — entities, edges, facts.

The Indexer writes to the graph. The worker and other agents read from it.
"""

from __future__ import annotations

import json

from pearscaff.db import _get_conn, _now, init_db


# --- Entity types ---


def list_entity_types() -> list[dict]:
    """Return all registered entity types."""
    init_db()
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, name, description, extract_fields, added_at FROM entity_types"
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["extract_fields"] = json.loads(d["extract_fields"]) if d["extract_fields"] else []
        result.append(d)
    return result


# --- Entities ---


def _next_entity_id(entity_type: str) -> str:
    conn = _get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as c FROM entities WHERE type = ?", (entity_type,)
    ).fetchone()
    num = row["c"] + 1
    return f"{entity_type}_{num:03d}"


def find_entity(
    entity_type: str, name: str, metadata_match: str | None = None
) -> dict | None:
    """Find an existing entity by exact name or metadata match.

    For persons: match on name, or email in metadata.
    For companies: match on name, or domain in metadata.
    """
    init_db()
    conn = _get_conn()

    # Exact name match
    row = conn.execute(
        "SELECT id, type, name, metadata, created_at FROM entities "
        "WHERE type = ? AND name = ?",
        (entity_type, name),
    ).fetchone()
    if row:
        d = dict(row)
        d["metadata"] = json.loads(d["metadata"]) if d["metadata"] else {}
        return d

    # Metadata match (e.g. email or domain)
    if metadata_match:
        row = conn.execute(
            "SELECT id, type, name, metadata, created_at FROM entities "
            "WHERE type = ? AND metadata LIKE ?",
            (entity_type, f"%{metadata_match}%"),
        ).fetchone()
        if row:
            d = dict(row)
            d["metadata"] = json.loads(d["metadata"]) if d["metadata"] else {}
            return d

    return None


def create_entity(entity_type: str, name: str, metadata: dict | None = None) -> str:
    """Create a new entity. Returns the entity ID."""
    init_db()
    conn = _get_conn()
    entity_id = _next_entity_id(entity_type)
    conn.execute(
        "INSERT INTO entities (id, type, name, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
        (entity_id, entity_type, name, json.dumps(metadata or {}), _now()),
    )
    conn.commit()
    return entity_id


def get_entity(entity_id: str) -> dict | None:
    """Look up an entity by ID."""
    init_db()
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, type, name, metadata, created_at FROM entities WHERE id = ?",
        (entity_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["metadata"] = json.loads(d["metadata"]) if d["metadata"] else {}
    return d


# --- Edges ---


def _next_edge_id() -> str:
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) as c FROM edges").fetchone()
    num = row["c"] + 1
    return f"edge_{num:03d}"


def create_edge(
    from_entity: str,
    to_entity: str,
    relationship: str,
    source_record: str,
) -> str:
    """Create a graph edge. Returns the edge ID."""
    init_db()
    conn = _get_conn()
    edge_id = _next_edge_id()
    conn.execute(
        "INSERT INTO edges (id, from_entity, to_entity, relationship, source_record, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (edge_id, from_entity, to_entity, relationship, source_record, _now()),
    )
    conn.commit()
    return edge_id


# --- Facts ---


def _next_fact_id() -> str:
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) as c FROM facts").fetchone()
    num = row["c"] + 1
    return f"fact_{num:03d}"


def upsert_fact(
    entity_id: str,
    attribute: str,
    value: str,
    source_record: str,
) -> str:
    """Insert or update a fact. Returns the fact ID."""
    init_db()
    conn = _get_conn()
    now = _now()

    # Check if fact already exists for this entity + attribute
    row = conn.execute(
        "SELECT id FROM facts WHERE entity_id = ? AND attribute = ?",
        (entity_id, attribute),
    ).fetchone()

    if row:
        fact_id = row["id"]
        conn.execute(
            "UPDATE facts SET value = ?, source_record = ?, updated_at = ? WHERE id = ?",
            (value, source_record, now, fact_id),
        )
    else:
        fact_id = _next_fact_id()
        conn.execute(
            "INSERT INTO facts (id, entity_id, attribute, value, source_record, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (fact_id, entity_id, attribute, value, source_record, now),
        )

    conn.commit()
    return fact_id
