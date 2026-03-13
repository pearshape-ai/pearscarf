"""Knowledge graph CRUD — entities, edges, facts.

The Indexer writes to the graph. The worker and other agents read from it.
"""

from __future__ import annotations

from psycopg.types.json import Jsonb

from pearscaff.db import _get_conn, _now, init_db


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


def _next_entity_id(entity_type: str) -> str:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM entities WHERE type = %s", (entity_type,)
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
    with _get_conn() as conn:
        # Exact name match
        row = conn.execute(
            "SELECT id, type, name, metadata, created_at FROM entities "
            "WHERE type = %s AND name = %s",
            (entity_type, name),
        ).fetchone()
        if row:
            d = dict(row)
            d["metadata"] = d["metadata"] if d["metadata"] else {}
            return d

        # Metadata match (e.g. email or domain) — cast JSONB to text for LIKE
        if metadata_match:
            row = conn.execute(
                "SELECT id, type, name, metadata, created_at FROM entities "
                "WHERE type = %s AND metadata::text LIKE %s",
                (entity_type, f"%{metadata_match}%"),
            ).fetchone()
            if row:
                d = dict(row)
                d["metadata"] = d["metadata"] if d["metadata"] else {}
                return d

    return None


def create_entity(entity_type: str, name: str, metadata: dict | None = None) -> str:
    """Create a new entity. Returns the entity ID."""
    init_db()
    entity_id = _next_entity_id(entity_type)
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO entities (id, type, name, metadata, created_at) VALUES (%s, %s, %s, %s, %s)",
            (entity_id, entity_type, name, Jsonb(metadata or {}), _now()),
        )
        conn.commit()
    return entity_id


def get_entity(entity_id: str) -> dict | None:
    """Look up an entity by ID."""
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, type, name, metadata, created_at FROM entities WHERE id = %s",
            (entity_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["metadata"] = d["metadata"] if d["metadata"] else {}
        return d


def search_entities(
    query: str,
    entity_type: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Search entities by name or metadata content.

    Matches exact name or LIKE on name and metadata fields.
    """
    init_db()
    with _get_conn() as conn:
        conditions = ["(name = %s OR name LIKE %s OR metadata::text LIKE %s)"]
        params: list = [query, f"%{query}%", f"%{query}%"]

        if entity_type:
            conditions.append("type = %s")
            params.append(entity_type)

        params.append(limit)

        where = " AND ".join(conditions)
        rows = conn.execute(
            f"SELECT id, type, name, metadata, created_at FROM entities "
            f"WHERE {where} ORDER BY created_at DESC LIMIT %s",
            params,
        ).fetchall()

        result = []
        for row in rows:
            d = dict(row)
            d["metadata"] = d["metadata"] if d["metadata"] else {}
            result.append(d)
        return result


# --- Edges ---


def _next_edge_id() -> str:
    with _get_conn() as conn:
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
    edge_id = _next_edge_id()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO edges (id, from_entity, to_entity, relationship, source_record, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (edge_id, from_entity, to_entity, relationship, source_record, _now()),
        )
        conn.commit()
    return edge_id


# --- Facts ---


def _next_fact_id() -> str:
    with _get_conn() as conn:
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
    now = _now()
    with _get_conn() as conn:
        # Check if fact already exists for this entity + attribute
        row = conn.execute(
            "SELECT id FROM facts WHERE entity_id = %s AND attribute = %s",
            (entity_id, attribute),
        ).fetchone()

        if row:
            fact_id = row["id"]
            conn.execute(
                "UPDATE facts SET value = %s, source_record = %s, updated_at = %s WHERE id = %s",
                (value, source_record, now, fact_id),
            )
        else:
            fact_id = _next_fact_id()
            conn.execute(
                "INSERT INTO facts (id, entity_id, attribute, value, source_record, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (fact_id, entity_id, attribute, value, source_record, now),
            )

        conn.commit()
    return fact_id


def get_entity_facts(entity_id: str) -> list[dict]:
    """Get all facts for an entity."""
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, attribute, value, source_record, updated_at "
            "FROM facts WHERE entity_id = %s ORDER BY updated_at DESC",
            (entity_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def traverse_graph(entity_id: str, max_depth: int = 3) -> dict:
    """Walk edges from an entity up to max_depth hops.

    Returns {entities: [...], edges: [...], source_records: [...]}.
    """
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            """
            WITH RECURSIVE connected AS (
                SELECT to_entity, relationship, source_record, 0 as depth
                FROM edges WHERE from_entity = %s
                UNION ALL
                SELECT e.to_entity, e.relationship, e.source_record, c.depth + 1
                FROM edges e JOIN connected c ON e.from_entity = c.to_entity
                WHERE c.depth < %s
            )
            SELECT DISTINCT to_entity, relationship, source_record, depth
            FROM connected
            """,
            (entity_id, max_depth),
        ).fetchall()

    entity_ids = set()
    edge_list = []
    source_records = set()

    for row in rows:
        entity_ids.add(row["to_entity"])
        edge_list.append({
            "to_entity": row["to_entity"],
            "relationship": row["relationship"],
            "source_record": row["source_record"],
            "depth": row["depth"],
        })
        if row["source_record"]:
            source_records.add(row["source_record"])

    # Fetch full entity details
    entities = []
    for eid in entity_ids:
        ent = get_entity(eid)
        if ent:
            entities.append(ent)

    return {
        "entities": entities,
        "edges": edge_list,
        "source_records": list(source_records),
    }
