"""Knowledge graph CRUD — entities, edges, facts.

The Indexer writes to the graph (Neo4j). The worker and other agents read from it.
list_entity_types() still reads from Postgres.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pearscaff.db import _get_conn, init_db
from pearscaff.neo4j_client import get_session

# Label map: extraction entity type string → Neo4j node label
_LABELS = {
    "person": "Person",
    "company": "Company",
    "project": "Project",
    "event": "Event",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Entity types (Postgres) ---


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
            d["extract_fields"] = d["extract_fields"] if d["extract_fields"] else []
            result.append(d)
        return result


# --- Entities ---


def find_entity(
    entity_type: str, name: str, metadata_match: str | None = None
) -> dict | None:
    """Find an existing entity by exact name (+ email/domain if provided)."""
    label = _LABELS.get(entity_type, entity_type.capitalize())

    with get_session() as session:
        # Try exact name match first
        result = session.run(
            f"MATCH (n:{label}) WHERE toLower(n.name) = toLower($name) RETURN n, elementId(n) AS eid LIMIT 1",
            name=name,
        )
        record = result.single()

        # For persons, also try matching by email
        if record is None and entity_type == "person" and metadata_match:
            result = session.run(
                f"MATCH (n:{label}) WHERE toLower(n.email) = toLower($email) RETURN n, elementId(n) AS eid LIMIT 1",
                email=metadata_match,
            )
            record = result.single()

        # For companies, also try matching by domain
        if record is None and entity_type == "company" and metadata_match:
            result = session.run(
                f"MATCH (n:{label}) WHERE toLower(n.domain) = toLower($domain) RETURN n, elementId(n) AS eid LIMIT 1",
                domain=metadata_match,
            )
            record = result.single()

        if record is None:
            return None

        node = record["n"]
        return {
            "id": record["eid"],
            "type": entity_type,
            "name": node.get("name", ""),
            "metadata": {k: v for k, v in dict(node).items() if k not in ("name", "created_at")},
        }


def create_entity(entity_type: str, name: str, metadata: dict | None = None) -> str:
    """Create or merge an entity. Returns the element ID."""
    label = _LABELS.get(entity_type, entity_type.capitalize())
    props = dict(metadata or {})
    props["name"] = name
    props["created_at"] = _now()

    with get_session() as session:
        # Build MERGE key based on entity type
        if entity_type == "person" and props.get("email"):
            # Merge on name + email for persons
            result = session.run(
                f"MERGE (n:{label} {{name: $name, email: $email}}) "
                "ON CREATE SET n += $props "
                "ON MATCH SET n += $update_props "
                "RETURN elementId(n) AS eid",
                name=name,
                email=props["email"],
                props=props,
                update_props={k: v for k, v in props.items() if k != "created_at"},
            )
        elif entity_type == "company" and props.get("domain"):
            result = session.run(
                f"MERGE (n:{label} {{name: $name, domain: $domain}}) "
                "ON CREATE SET n += $props "
                "ON MATCH SET n += $update_props "
                "RETURN elementId(n) AS eid",
                name=name,
                domain=props["domain"],
                props=props,
                update_props={k: v for k, v in props.items() if k != "created_at"},
            )
        else:
            result = session.run(
                f"MERGE (n:{label} {{name: $name}}) "
                "ON CREATE SET n += $props "
                "ON MATCH SET n += $update_props "
                "RETURN elementId(n) AS eid",
                name=name,
                props=props,
                update_props={k: v for k, v in props.items() if k != "created_at"},
            )

        record = result.single()
        return record["eid"]


def get_entity(entity_id: str) -> dict | None:
    """Look up an entity by element ID."""
    with get_session() as session:
        result = session.run(
            "MATCH (n) WHERE elementId(n) = $eid RETURN n, elementId(n) AS eid, labels(n) AS lbls",
            eid=entity_id,
        )
        record = result.single()
        if record is None:
            return None

        node = record["n"]
        labels = record["lbls"]
        # Derive type from label
        entity_type = "unknown"
        for ext_type, lbl in _LABELS.items():
            if lbl in labels:
                entity_type = ext_type
                break

        return {
            "id": record["eid"],
            "type": entity_type,
            "name": node.get("name", ""),
            "metadata": {k: v for k, v in dict(node).items() if k not in ("name", "created_at")},
            "created_at": node.get("created_at", ""),
        }


def search_entities(
    query: str,
    entity_type: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Search entities by name, email, or domain."""
    with get_session() as session:
        if entity_type:
            label = _LABELS.get(entity_type, entity_type.capitalize())
            result = session.run(
                f"MATCH (n:{label}) "
                "WHERE toLower(n.name) CONTAINS toLower($q) "
                "   OR toLower(coalesce(n.email, '')) CONTAINS toLower($q) "
                "   OR toLower(coalesce(n.domain, '')) CONTAINS toLower($q) "
                "RETURN n, elementId(n) AS eid, labels(n) AS lbls "
                "LIMIT $limit",
                q=query,
                limit=limit,
            )
        else:
            result = session.run(
                "MATCH (n) WHERE n.name IS NOT NULL AND ("
                "  toLower(n.name) CONTAINS toLower($q) "
                "  OR toLower(coalesce(n.email, '')) CONTAINS toLower($q) "
                "  OR toLower(coalesce(n.domain, '')) CONTAINS toLower($q)"
                ") "
                "RETURN n, elementId(n) AS eid, labels(n) AS lbls "
                "LIMIT $limit",
                q=query,
                limit=limit,
            )

        entities = []
        for record in result:
            node = record["n"]
            labels = record["lbls"]
            etype = "unknown"
            for ext_type, lbl in _LABELS.items():
                if lbl in labels:
                    etype = ext_type
                    break
            entities.append({
                "id": record["eid"],
                "type": etype,
                "name": node.get("name", ""),
                "metadata": {k: v for k, v in dict(node).items() if k not in ("name", "created_at")},
            })
        return entities


# --- Edges ---


def create_edge(
    from_entity: str,
    to_entity: str,
    relationship: str,
    source_record: str,
    valid_at: str | None = None,
) -> str:
    """Create a relationship between two entities. Returns the relationship element ID."""
    rel_type = relationship.upper()
    ts = _now()
    props = {
        "source_record": source_record,
        "created_at": ts,
        "valid_at": valid_at or ts,
        "invalid_at": None,
    }

    with get_session() as session:
        # Use APOC for dynamic relationship type
        result = session.run(
            "MATCH (a) WHERE elementId(a) = $from_id "
            "MATCH (b) WHERE elementId(b) = $to_id "
            "CALL apoc.create.relationship(a, $rel_type, $props, b) "
            "YIELD rel "
            "RETURN elementId(rel) AS rid",
            from_id=from_entity,
            to_id=to_entity,
            rel_type=rel_type,
            props=props,
        )
        record = result.single()
        return record["rid"] if record else ""


def invalidate_edge(edge_id: str, invalid_at: str | None = None) -> None:
    """Set invalid_at on an existing relationship."""
    ts = invalid_at or _now()
    with get_session() as session:
        session.run(
            "MATCH ()-[r]->() WHERE elementId(r) = $rid "
            "SET r.invalid_at = $ts",
            rid=edge_id,
            ts=ts,
        )


# --- Facts ---


def upsert_fact(
    entity_id: str,
    claim: str,
    confidence: str,
    source_record: str,
    valid_at: str | None = None,
) -> str:
    """Invalidate-and-create: close the old fact (if any) and create a new one.

    Returns the new Fact element ID.
    """
    ts = _now()
    vat = valid_at or ts

    with get_session() as session:
        # Step 1: Find existing current fact with same claim on this entity
        existing = session.run(
            "MATCH (n)-[:HAS_FACT]->(f:Fact {claim: $claim}) "
            "WHERE elementId(n) = $eid AND f.invalid_at IS NULL "
            "RETURN elementId(f) AS fid",
            eid=entity_id,
            claim=claim,
        ).single()

        # Step 2: Invalidate old fact if it exists
        if existing:
            session.run(
                "MATCH (f:Fact) WHERE elementId(f) = $fid "
                "SET f.invalid_at = $ts",
                fid=existing["fid"],
                ts=vat,
            )

        # Step 3: Create new fact
        result = session.run(
            "MATCH (n) WHERE elementId(n) = $eid "
            "CREATE (n)-[:HAS_FACT]->(f:Fact {"
            "  claim: $claim, confidence: $confidence, "
            "  source_record: $source, created_at: $created, "
            "  valid_at: $valid_at, invalid_at: null"
            "}) "
            "RETURN elementId(f) AS fid",
            eid=entity_id,
            claim=claim,
            confidence=confidence,
            source=source_record,
            created=ts,
            valid_at=vat,
        )
        record = result.single()
        return record["fid"] if record else ""


def get_entity_facts(entity_id: str, current_only: bool = True) -> list[dict]:
    """Get facts for an entity. By default only current (non-invalidated) facts."""
    with get_session() as session:
        where = "WHERE elementId(n) = $eid"
        if current_only:
            where += " AND f.invalid_at IS NULL"
        result = session.run(
            f"MATCH (n)-[:HAS_FACT]->(f:Fact) {where} "
            "RETURN f, elementId(f) AS fid",
            eid=entity_id,
        )
        facts = []
        for record in result:
            fnode = record["f"]
            facts.append({
                "id": record["fid"],
                "claim": fnode.get("claim", ""),
                "confidence": fnode.get("confidence", ""),
                "source_record": fnode.get("source_record", ""),
                "created_at": fnode.get("created_at", ""),
                "valid_at": fnode.get("valid_at", ""),
                "invalid_at": fnode.get("invalid_at"),
            })
        return facts


# --- Traversal ---


def traverse_graph(entity_id: str, max_depth: int = 3, current_only: bool = True) -> dict:
    """Walk relationships from an entity up to max_depth hops.

    When current_only is True (default), only traverse edges where invalid_at IS NULL.
    """
    with get_session() as session:
        where_clause = "WHERE elementId(start) = $eid AND NOT connected:Fact"
        if current_only:
            where_clause += " AND ALL(r IN relationships(path) WHERE r.invalid_at IS NULL)"

        result = session.run(
            f"MATCH path = (start)-[*1..$depth]-(connected) "
            f"{where_clause} "
            "UNWIND relationships(path) AS r "
            "WITH start, connected, r, startNode(r) AS sn, endNode(r) AS en "
            "RETURN DISTINCT "
            "  elementId(connected) AS connected_id, "
            "  connected.name AS connected_name, "
            "  labels(connected) AS connected_labels, "
            "  type(r) AS rel_type, "
            "  r.source_record AS source_record, "
            "  r.valid_at AS valid_at, "
            "  r.invalid_at AS invalid_at, "
            "  elementId(sn) AS from_id, "
            "  elementId(en) AS to_id",
            eid=entity_id,
            depth=max_depth,
        )

        entities = []
        edges = []
        source_records = set()
        seen_entities = set()

        for record in result:
            cid = record["connected_id"]
            if cid not in seen_entities:
                seen_entities.add(cid)
                labels = record["connected_labels"]
                etype = "unknown"
                for ext_type, lbl in _LABELS.items():
                    if lbl in labels:
                        etype = ext_type
                        break
                entities.append({
                    "id": cid,
                    "type": etype,
                    "name": record["connected_name"] or "",
                })

            edges.append({
                "from": record["from_id"],
                "to": record["to_id"],
                "relationship": record["rel_type"],
                "source_record": record["source_record"],
                "valid_at": record["valid_at"] or "",
                "invalid_at": record["invalid_at"],
            })

            if record["source_record"]:
                source_records.add(record["source_record"])

        return {
            "entities": entities,
            "edges": edges,
            "source_records": list(source_records),
        }


# --- Stats ---


def graph_stats() -> dict:
    """Count nodes by label, relationships by type, total facts."""
    with get_session() as session:
        # Count nodes by label (exclude Fact nodes)
        entity_counts = {}
        total_entities = 0
        for ext_type, label in _LABELS.items():
            result = session.run(f"MATCH (n:{label}) RETURN count(n) AS c")
            count = result.single()["c"]
            if count > 0:
                entity_counts[ext_type] = count
            total_entities += count

        # Count facts
        result = session.run("MATCH (f:Fact) RETURN count(f) AS c")
        total_facts = result.single()["c"]

        result = session.run("MATCH (f:Fact) WHERE f.invalid_at IS NULL RETURN count(f) AS c")
        current_facts = result.single()["c"]

        # Count relationships by type (exclude HAS_FACT)
        result = session.run(
            "MATCH ()-[r]->() WHERE type(r) <> 'HAS_FACT' "
            "RETURN type(r) AS rel_type, count(r) AS c ORDER BY c DESC"
        )
        rel_counts = {}
        total_edges = 0
        for record in result:
            rel_counts[record["rel_type"]] = record["c"]
            total_edges += record["c"]

        return {
            "total_entities": total_entities,
            "total_edges": total_edges,
            "total_facts": total_facts,
            "current_facts": current_facts,
            "entity_counts": entity_counts,
            "rel_counts": rel_counts,
        }


# --- Source record lookup ---


def get_nodes_by_source_record(record_id: str) -> list[dict]:
    """Find all relationships and facts sourced from a specific record."""
    items = []

    with get_session() as session:
        # Relationships with this source_record
        result = session.run(
            "MATCH (a)-[r]->(b) "
            "WHERE r.source_record = $rid AND type(r) <> 'HAS_FACT' "
            "RETURN a.name AS from_name, type(r) AS relationship, b.name AS to_name, "
            "r.valid_at AS valid_at, r.invalid_at AS invalid_at",
            rid=record_id,
        )
        for record in result:
            items.append({
                "type": "relationship",
                "from": record["from_name"] or "?",
                "relationship": record["relationship"],
                "to": record["to_name"] or "?",
                "valid_at": record["valid_at"] or "",
                "invalid_at": record["invalid_at"],
            })

        # Facts with this source_record
        result = session.run(
            "MATCH (n)-[:HAS_FACT]->(f:Fact) "
            "WHERE f.source_record = $rid "
            "RETURN n.name AS entity_name, f.claim AS claim, f.confidence AS confidence, "
            "f.valid_at AS valid_at, f.invalid_at AS invalid_at",
            rid=record_id,
        )
        for record in result:
            items.append({
                "type": "fact",
                "entity_name": record["entity_name"] or "?",
                "attribute": "claim",
                "value": record["claim"] or "",
                "valid_at": record["valid_at"] or "",
                "invalid_at": record["invalid_at"],
            })

    return items


# --- Temporal migration ---


def retrofit_temporal() -> dict:
    """Add temporal timestamps to existing edges and facts that lack them.

    Sets valid_at = created_at (or now), invalid_at = null. Returns counts.
    One-time migration for pre-1.7.0 data.
    """
    ts = _now()
    with get_session() as session:
        # Retrofit relationships (non-HAS_FACT)
        result = session.run(
            "MATCH ()-[r]->() "
            "WHERE r.valid_at IS NULL AND type(r) <> 'HAS_FACT' "
            "SET r.valid_at = coalesce(r.created_at, $ts), "
            "    r.invalid_at = null "
            "RETURN count(r) AS c",
            ts=ts,
        )
        edges = result.single()["c"]

        # Retrofit facts
        result = session.run(
            "MATCH (n)-[:HAS_FACT]->(f:Fact) "
            "WHERE f.valid_at IS NULL "
            "SET f.valid_at = coalesce(f.created_at, $ts), "
            "    f.invalid_at = null "
            "RETURN count(f) AS c",
            ts=ts,
        )
        facts = result.single()["c"]

        return {"edges_retrofitted": edges, "facts_retrofitted": facts}
