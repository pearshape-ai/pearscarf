"""Knowledge graph CRUD — entities, edges, facts.

The Indexer writes to the graph (Neo4j). The worker and other agents read from it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from pearscarf.config import TIMEZONE
from pearscarf.neo4j_client import get_session

# Label map: extraction entity type string → Neo4j node label
_LABELS = {
    "person": "Person",
    "company": "Company",
    "project": "Project",
    "event": "Event",
}

# Edge labels → valid fact_type values per label.
FACT_CATEGORIES = {
    "AFFILIATED": [
        "employee", "contractor", "advisor", "board_member", "founder",
        "investor", "legal_counsel", "consultant", "owner", "contributor",
        "reviewer", "stakeholder", "subsidiary", "sub_project", "other",
    ],
    "ASSERTED": [
        "commitment", "promise", "decision", "evaluation", "opinion",
        "concern", "blocker", "request", "update", "risk", "goal",
        "reference", "other",
    ],
    "TRANSITIONED": [
        "status_change", "stage_change", "role_change", "ownership_change",
        "resolution", "completion", "cancellation", "other",
    ],
}

# System-only edge type — not from extraction.
IDENTIFIED_AS = "IDENTIFIED_AS"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_to_local_date(utc_dt: str | datetime) -> str:
    """Convert a UTC datetime to a local date string (e.g. '2026-03-21').

    Uses the configured TIMEZONE to determine which calendar day
    a UTC timestamp falls on locally.
    """
    if isinstance(utc_dt, str):
        utc_dt = datetime.fromisoformat(utc_dt)
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    local_dt = utc_dt.astimezone(ZoneInfo(TIMEZONE))
    return local_dt.date().isoformat()


def get_or_create_day(date_str: str) -> str:
    """Find or create a Day node for the given date. Returns the element ID.

    date_str should be an ISO date string like '2026-03-21'.
    """
    with get_session() as session:
        result = session.run(
            "MERGE (d:Day {date: $date}) "
            "ON CREATE SET d.created_at = $ts "
            "RETURN elementId(d) AS did",
            date=date_str,
            ts=_now(),
        )
        record = result.single()
        return record["did"] if record else ""


def ensure_constraints() -> None:
    """Create Neo4j indexes and constraints if they don't exist."""
    with get_session() as session:
        session.run(
            "CREATE CONSTRAINT day_date_unique IF NOT EXISTS "
            "FOR (d:Day) REQUIRE d.date IS UNIQUE"
        )


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


def _label_to_type(labels: list[str]) -> str:
    """Convert Neo4j labels list to entity type string."""
    for label in labels:
        lower = label.lower()
        if lower in ("person", "company", "project", "event"):
            return lower
    return ""


def _find_by_identified_as(name: str) -> list[dict]:
    """Find entities that have an IDENTIFIED_AS edge where surface_form matches name."""
    with get_session() as session:
        result = session.run(
            "MATCH (n)-[r:IDENTIFIED_AS]->(m) "
            "WHERE toLower(r.fact) CONTAINS toLower($name) "
            "   OR toLower(coalesce(r.surface_form, '')) = toLower($name) "
            "RETURN n, elementId(n) AS eid, labels(n) AS lbls",
            name=name,
        )
        entities = []
        for record in result:
            node = record["n"]
            etype = _label_to_type(record["lbls"])
            entities.append({
                "id": record["eid"],
                "type": etype,
                "name": node.get("name", ""),
                "metadata": {
                    k: v for k, v in dict(node).items()
                    if k not in ("name", "created_at")
                },
            })
        return entities


def find_entity_candidates(
    entity_type: str,
    name: str,
    metadata: dict | None = None,
) -> list[dict]:
    """Broad candidate retrieval for entity resolution.

    Searches multiple paths in order of confidence. Deduplicates by element ID.
    Returns list of candidate dicts: {"id", "type", "name", "metadata"}.
    Empty list if no candidates found.
    """
    if not name:
        return []

    metadata = metadata or {}
    seen: set[str] = set()
    candidates: list[dict] = []

    def _add(entity: dict) -> None:
        eid = entity["id"]
        if eid not in seen:
            seen.add(eid)
            candidates.append(entity)

    label = _LABELS.get(entity_type, entity_type.capitalize())

    # 1. Exact name match
    existing = find_entity(entity_type, name)
    if existing:
        _add(existing)

    # 2. Email match for persons
    if entity_type == "person" and metadata.get("email"):
        existing = find_entity(entity_type, name, metadata_match=metadata["email"])
        if existing:
            _add(existing)

    # 3. Domain match for companies
    if entity_type == "company" and metadata.get("domain"):
        existing = find_entity(entity_type, name, metadata_match=metadata["domain"])
        if existing:
            _add(existing)

    # 4. First-name prefix match for persons (single token names like "David", "Jim")
    if entity_type == "person" and " " not in name.strip():
        with get_session() as session:
            result = session.run(
                f"MATCH (n:{label}) "
                "WHERE toLower(n.name) STARTS WITH toLower($prefix) "
                "RETURN n, elementId(n) AS eid "
                "LIMIT 5",
                prefix=name.strip(),
            )
            for record in result:
                node = record["n"]
                _add({
                    "id": record["eid"],
                    "type": entity_type,
                    "name": node.get("name", ""),
                    "metadata": {
                        k: v for k, v in dict(node).items()
                        if k not in ("name", "created_at")
                    },
                })

    # 5. Substring name match via search_entities()
    for entity in search_entities(name, entity_type=entity_type, limit=5):
        _add(entity)

    # 6. IDENTIFIED_AS edge match
    for entity in _find_by_identified_as(name):
        _add(entity)

    return candidates


def get_entity_context(entity_id: str, max_facts: int = 10, max_connections: int = 10) -> dict:
    """Build a context package for an entity — facts and 1-hop connections.

    Used by the resolution judge to distinguish between candidate entities.
    Only current (non-stale) facts are included.
    """
    entity = get_entity(entity_id)
    if not entity:
        return {"entity": {}, "facts": [], "connections": []}

    # Facts — current only, limited, sorted by source_at descending
    all_facts = get_facts_for_entity(entity_id, include_stale=False)
    all_facts.sort(key=lambda f: f.get("source_at", ""), reverse=True)
    facts = [
        {
            "edge_label": f["edge_label"],
            "fact_type": f["fact_type"],
            "fact": f["fact"],
            "other_name": f["other_name"],
            "confidence": f["confidence"],
        }
        for f in all_facts[:max_facts]
    ]

    # Connections — 1-hop traversal, current edges only
    traversal = traverse_fact_edges(entity_id, max_depth=1, current_only=True)
    connections = []
    seen_names: set[str] = set()
    for node in traversal.get("nodes", []):
        name = node.get("name", "")
        if name and name not in seen_names and node.get("type") != "day":
            seen_names.add(name)
            connections.append({"name": name, "type": node.get("type", "")})
        if len(connections) >= max_connections:
            break

    return {
        "entity": entity,
        "facts": facts,
        "connections": connections,
    }


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
        entity_type = _label_to_type(labels) or "unknown"

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
            etype = _label_to_type(record["lbls"])
            entities.append({
                "id": record["eid"],
                "type": etype,
                "name": node.get("name", ""),
                "metadata": {k: v for k, v in dict(node).items() if k not in ("name", "created_at")},
            })
        return entities


# --- Fact Edges ---


def create_fact_edge(
    from_node_id: str,
    to_node_id: str,
    edge_label: str,
    fact_type: str,
    fact: str,
    confidence: str,
    source_record: str,
    source_type: str,
    source_at: str | None = None,
    valid_until: str | None = None,
) -> str:
    """Create a fact-edge between two nodes. Returns the edge element ID.

    edge_label: AFFILIATED, ASSERTED, or TRANSITIONED (used as Neo4j relationship type).
    fact_type: specific type within the label (e.g. employee, commitment, status_change).
    source_at: event time — when the fact became true in the world.
    valid_until: optional deadline/expiry.
    """
    ts = _now()
    props = {
        "fact": fact,
        "fact_type": fact_type,
        "confidence": confidence,
        "source_record": source_record,
        "source_records": [source_record],
        "source_type": source_type,
        "source_at": source_at or ts,
        "recorded_at": ts,
        "stale": False,
        "replaced_by": None,
        "valid_until": valid_until,
        "created_at": ts,
    }

    with get_session() as session:
        result = session.run(
            "MATCH (a) WHERE elementId(a) = $from_id "
            "MATCH (b) WHERE elementId(b) = $to_id "
            "CALL apoc.create.relationship(a, $rel_type, $props, b) "
            "YIELD rel "
            "RETURN elementId(rel) AS rid",
            from_id=from_node_id,
            to_id=to_node_id,
            rel_type=edge_label.upper(),
            props=props,
        )
        record = result.single()
        return record["rid"] if record else ""


def find_existing_fact_edge(
    from_id: str,
    edge_label: str,
    fact_type: str,
    to_id: str,
) -> dict | None:
    """Find an active (non-stale) fact-edge between two nodes.

    Returns {"id", "fact", "source_at", "stale"} or None.
    """
    with get_session() as session:
        result = session.run(
            "MATCH (a)-[r]->(b) "
            "WHERE elementId(a) = $from_id AND elementId(b) = $to_id "
            "AND type(r) = $label AND r.fact_type = $ft "
            "AND (r.stale IS NULL OR r.stale = false) AND r.replaced_by IS NULL "
            "RETURN elementId(r) AS rid, r.fact AS fact, "
            "r.source_at AS source_at, r.stale AS stale "
            "LIMIT 1",
            from_id=from_id,
            to_id=to_id,
            label=edge_label.upper(),
            ft=fact_type,
        )
        record = result.single()
        if record is None:
            return None
        return {
            "id": record["rid"],
            "fact": record["fact"] or "",
            "source_at": record["source_at"] or "",
            "stale": record["stale"] or False,
        }


def find_exact_dup_edge(
    from_id: str,
    edge_label: str,
    fact_type: str,
    to_id: str,
    source_record: str,
    fact: str,
) -> str | None:
    """Find a literal duplicate edge — same from, to, label, type, source, and fact text.

    Returns edge element ID if found, None otherwise.
    """
    with get_session() as session:
        result = session.run(
            "MATCH (a)-[r]->(b) "
            "WHERE elementId(a) = $from_id AND elementId(b) = $to_id "
            "AND type(r) = $label AND r.fact_type = $ft "
            "AND r.source_record = $sr AND r.fact = $fact "
            "RETURN elementId(r) AS rid "
            "LIMIT 1",
            from_id=from_id,
            to_id=to_id,
            label=edge_label.upper(),
            ft=fact_type,
            sr=source_record,
            fact=fact,
        )
        record = result.single()
        return record["rid"] if record else None


def append_source_record(edge_id: str, source_record: str) -> None:
    """Append a source_record to an edge's source_records list if not already present."""
    with get_session() as session:
        session.run(
            "MATCH ()-[r]->() WHERE elementId(r) = $rid "
            "SET r.source_records = CASE "
            "  WHEN r.source_records IS NULL THEN [$sr] "
            "  WHEN NOT $sr IN r.source_records THEN r.source_records + $sr "
            "  ELSE r.source_records "
            "END",
            rid=edge_id,
            sr=source_record,
        )


def create_identified_as_edge(
    entity_id: str,
    surface_form: str,
    source_record: str,
    source_type: str,
    confidence: str,
    reasoning: str = "",
) -> str:
    """Write or update an IDENTIFIED_AS self-edge for a resolved surface form.

    MERGE on (entity, surface_form) — one edge per unique alias.
    On first creation: sets all properties.
    On subsequent match: updates resolved_at, appends source_record to source_records.
    """
    ts = _now()

    with get_session() as session:
        # Try to find existing edge with same surface_form
        result = session.run(
            "MATCH (a)-[r:IDENTIFIED_AS]->(a) "
            "WHERE elementId(a) = $eid AND r.surface_form = $sf "
            "RETURN elementId(r) AS rid, r.source_records AS existing_records",
            eid=entity_id,
            sf=surface_form,
        )
        existing = result.single()

        if existing:
            # Update existing edge
            existing_records = existing["existing_records"] or []
            if source_record not in existing_records:
                existing_records.append(source_record)
            session.run(
                "MATCH (a)-[r:IDENTIFIED_AS]->(a) "
                "WHERE elementId(a) = $eid AND r.surface_form = $sf "
                "SET r.resolved_at = $ts, r.source_records = $records",
                eid=entity_id,
                sf=surface_form,
                ts=ts,
                records=existing_records,
            )
            return existing["rid"]
        else:
            # Create new edge
            result = session.run(
                "MATCH (a) WHERE elementId(a) = $eid "
                "CALL apoc.create.relationship(a, 'IDENTIFIED_AS', $props, a) "
                "YIELD rel "
                "RETURN elementId(rel) AS rid",
                eid=entity_id,
                props={
                    "fact": f"{surface_form} identified as this entity",
                    "surface_form": surface_form,
                    "category": "IDENTIFIED_AS",
                    "confidence": confidence,
                    "source_record": source_record,
                    "source_records": [source_record],
                    "source_type": source_type,
                    "reasoning": reasoning,
                    "resolved_at": ts,
                    "created_at": ts,
                    "invalid_at": None,
                },
            )
            record = result.single()
            return record["rid"] if record else ""


def mark_fact_stale(edge_id: str, replaced_by_id: str | None = None) -> None:
    """Mark a fact-edge as stale. Preserves the edge — history is kept."""
    with get_session() as session:
        session.run(
            "MATCH ()-[r]->() WHERE elementId(r) = $rid "
            "SET r.stale = true, r.replaced_by = $rby",
            rid=edge_id,
            rby=replaced_by_id,
        )


def get_facts_for_entity(
    entity_id: str, include_stale: bool = False,
) -> list[dict]:
    """Get all fact-edges connected to an entity (as source or target).

    By default only current facts (stale = false).
    """
    with get_session() as session:
        where = "WHERE elementId(n) = $eid AND r.fact IS NOT NULL"
        if not include_stale:
            where += " AND (r.stale IS NULL OR r.stale = false)"

        result = session.run(
            f"MATCH (n)-[r]-(other) {where} "
            "RETURN elementId(r) AS rid, type(r) AS edge_label, "
            "r.fact_type AS fact_type, "
            "r.fact AS fact, r.confidence AS confidence, "
            "r.source_record AS source_record, r.source_type AS source_type, "
            "r.source_at AS source_at, r.recorded_at AS recorded_at, "
            "r.stale AS stale, r.replaced_by AS replaced_by, "
            "r.valid_until AS valid_until, r.created_at AS created_at, "
            "elementId(other) AS other_id, other.name AS other_name, "
            "other.date AS other_date, labels(other) AS other_labels",
            eid=entity_id,
        )

        facts = []
        for record in result:
            other_labels = record["other_labels"] or []
            if "Day" in other_labels:
                other_display = record["other_date"] or "?"
            else:
                other_display = record["other_name"] or "?"
            facts.append({
                "id": record["rid"],
                "edge_label": record["edge_label"],
                "fact_type": record["fact_type"] or "",
                "fact": record["fact"],
                "confidence": record["confidence"] or "",
                "source_record": record["source_record"] or "",
                "source_type": record["source_type"] or "",
                "source_at": record["source_at"] or "",
                "recorded_at": record["recorded_at"] or "",
                "stale": record["stale"] or False,
                "replaced_by": record["replaced_by"],
                "valid_until": record["valid_until"],
                "created_at": record["created_at"] or "",
                "other_id": record["other_id"],
                "other_name": other_display,
            })
        return facts


def get_facts_for_day(date_str: str) -> list[dict]:
    """Get all fact-edges connected to a Day node.

    Only returns single-entity facts anchored to this day.
    Two-entity facts that happened on this day are found via source_at filtering.
    """
    with get_session() as session:
        result = session.run(
            "MATCH (entity)-[r]-(d:Day {date: $date}) "
            "WHERE r.fact IS NOT NULL "
            "RETURN elementId(r) AS rid, type(r) AS edge_label, "
            "r.fact_type AS fact_type, "
            "r.fact AS fact, r.confidence AS confidence, "
            "r.source_record AS source_record, r.source_type AS source_type, "
            "r.source_at AS source_at, r.recorded_at AS recorded_at, "
            "r.stale AS stale, r.replaced_by AS replaced_by, "
            "r.valid_until AS valid_until, r.created_at AS created_at, "
            "elementId(entity) AS entity_id, entity.name AS entity_name, "
            "labels(entity) AS entity_labels",
            date=date_str,
        )

        facts = []
        for record in result:
            etype = _label_to_type(record["entity_labels"] or [])
            facts.append({
                "id": record["rid"],
                "edge_label": record["edge_label"],
                "fact_type": record["fact_type"] or "",
                "fact": record["fact"],
                "confidence": record["confidence"] or "",
                "source_record": record["source_record"] or "",
                "source_type": record["source_type"] or "",
                "source_at": record["source_at"] or "",
                "recorded_at": record["recorded_at"] or "",
                "stale": record["stale"] or False,
                "replaced_by": record["replaced_by"],
                "valid_until": record["valid_until"],
                "created_at": record["created_at"] or "",
                "entity_id": record["entity_id"],
                "entity_name": record["entity_name"] or "?",
                "entity_type": etype,
            })
        return facts


# --- Traversal ---


def traverse_fact_edges(
    entity_id: str,
    max_depth: int = 3,
    current_only: bool = True,
    edge_labels: list[str] | None = None,
) -> dict:
    """Walk fact-edges from an entity up to max_depth hops.

    Returns connected entities/Day nodes and the fact-edges connecting them.
    When current_only is True (default), only traverses non-stale edges.
    Optional edge_labels filter limits traversal to AFFILIATED/ASSERTED/TRANSITIONED.
    """
    with get_session() as session:
        where_parts = ["elementId(start) = $eid"]
        if current_only:
            where_parts.append(
                "ALL(r IN relationships(path) WHERE r.stale IS NULL OR r.stale = false)"
            )
        if edge_labels:
            where_parts.append(
                "ALL(r IN relationships(path) WHERE type(r) IN $labels)"
            )
        where_clause = "WHERE " + " AND ".join(where_parts)

        params: dict = {"eid": entity_id}
        if edge_labels:
            params["labels"] = [l.upper() for l in edge_labels]

        result = session.run(
            f"MATCH path = (start)-[*1..{max_depth}]-(connected) "
            f"{where_clause} "
            "UNWIND relationships(path) AS r "
            "WITH start, connected, r, startNode(r) AS sn, endNode(r) AS en "
            "RETURN DISTINCT "
            "  elementId(connected) AS connected_id, "
            "  connected.name AS connected_name, "
            "  connected.date AS connected_date, "
            "  labels(connected) AS connected_labels, "
            "  type(r) AS edge_label, "
            "  r.fact_type AS fact_type, "
            "  r.fact AS fact, "
            "  r.confidence AS confidence, "
            "  r.source_record AS source_record, "
            "  r.source_type AS source_type, "
            "  r.source_at AS source_at, "
            "  r.stale AS stale, "
            "  r.replaced_by AS replaced_by, "
            "  elementId(sn) AS from_id, "
            "  elementId(en) AS to_id",
            **params,
        )

        nodes = []
        edges = []
        source_records = set()
        seen_nodes = set()

        for record in result:
            cid = record["connected_id"]
            if cid not in seen_nodes:
                seen_nodes.add(cid)
                labels = record["connected_labels"] or []
                if "Day" in labels:
                    nodes.append({
                        "id": cid,
                        "type": "day",
                        "name": record["connected_date"] or "?",
                    })
                else:
                    etype = _label_to_type(labels)
                    nodes.append({
                        "id": cid,
                        "type": etype,
                        "name": record["connected_name"] or "?",
                    })

            edges.append({
                "from": record["from_id"],
                "to": record["to_id"],
                "edge_label": record["edge_label"],
                "fact_type": record["fact_type"] or "",
                "fact": record["fact"] or "",
                "confidence": record["confidence"] or "",
                "source_record": record["source_record"] or "",
                "source_at": record["source_at"] or "",
                "stale": record["stale"] or False,
                "replaced_by": record["replaced_by"],
            })

            if record["source_record"]:
                source_records.add(record["source_record"])

        return {
            "nodes": nodes,
            "edges": edges,
            "source_records": list(source_records),
        }


# --- Stats ---


def graph_stats() -> dict:
    """Count nodes by label, fact-edges by edge_label and fact_type."""
    with get_session() as session:
        # Count entity nodes by label
        entity_counts = {}
        total_entities = 0
        for ext_type, label in _LABELS.items():
            result = session.run(f"MATCH (n:{label}) RETURN count(n) AS c")
            count = result.single()["c"]
            if count > 0:
                entity_counts[ext_type] = count
            total_entities += count

        # Count Day nodes
        result = session.run("MATCH (d:Day) RETURN count(d) AS c")
        day_count = result.single()["c"]

        # Count fact-edges by edge_label
        result = session.run(
            "MATCH ()-[r]->() WHERE r.fact IS NOT NULL "
            "RETURN type(r) AS edge_label, count(r) AS c, "
            "sum(CASE WHEN r.stale IS NULL OR r.stale = false THEN 1 ELSE 0 END) AS current_c "
            "ORDER BY c DESC"
        )
        edge_label_counts = {}
        total_facts = 0
        current_facts = 0
        for record in result:
            edge_label_counts[record["edge_label"]] = record["c"]
            total_facts += record["c"]
            current_facts += record["current_c"]

        # Count by fact_type
        result = session.run(
            "MATCH ()-[r]->() WHERE r.fact IS NOT NULL AND r.fact_type IS NOT NULL "
            "RETURN r.fact_type AS fact_type, count(r) AS c "
            "ORDER BY c DESC"
        )
        fact_type_counts = {}
        for record in result:
            fact_type_counts[record["fact_type"]] = record["c"]

        return {
            "total_entities": total_entities,
            "day_nodes": day_count,
            "total_facts": total_facts,
            "current_facts": current_facts,
            "entity_counts": entity_counts,
            "edge_label_counts": edge_label_counts,
            "fact_type_counts": fact_type_counts,
        }


# --- Source record lookup ---


def get_nodes_by_source_record(record_id: str) -> list[dict]:
    """Find all fact-edges sourced from a specific record."""
    with get_session() as session:
        result = session.run(
            "MATCH (a)-[r]->(b) "
            "WHERE r.source_record = $rid AND r.fact IS NOT NULL "
            "RETURN a.name AS from_name, a.date AS from_date, labels(a) AS from_labels, "
            "type(r) AS edge_label, r.fact_type AS fact_type, "
            "r.fact AS fact, r.confidence AS confidence, "
            "r.source_at AS source_at, r.stale AS stale, "
            "b.name AS to_name, b.date AS to_date, labels(b) AS to_labels",
            rid=record_id,
        )
        items = []
        for record in result:
            from_labels = record["from_labels"] or []
            to_labels = record["to_labels"] or []
            from_display = record["from_date"] if "Day" in from_labels else (record["from_name"] or "?")
            to_display = record["to_date"] if "Day" in to_labels else (record["to_name"] or "?")
            items.append({
                "type": "fact",
                "edge_label": record["edge_label"],
                "fact_type": record["fact_type"] or "",
                "fact": record["fact"] or "",
                "from": from_display,
                "to": to_display,
                "confidence": record["confidence"] or "",
                "source_at": record["source_at"] or "",
                "stale": record["stale"] or False,
            })
        return items


def get_edges_by_source_record(record_id: str) -> list[dict]:
    """Get fact-edges where record_id appears in source_records, with element IDs.

    Uses source_records (list) instead of source_record (singular) so edges
    that were dedup-merged from this record are also returned.
    """
    with get_session() as session:
        result = session.run(
            "MATCH (a)-[r]->(b) "
            "WHERE $rid IN r.source_records AND r.fact IS NOT NULL "
            "RETURN elementId(r) AS edge_id, type(r) AS edge_label, "
            "r.fact_type AS fact_type, r.fact AS fact, "
            "r.confidence AS confidence, r.source_at AS source_at, "
            "r.source_record AS source_record, r.source_records AS source_records, "
            "r.stale AS stale, r.role AS role, "
            "elementId(a) AS from_id, a.name AS from_name, "
            "elementId(b) AS to_id, b.name AS to_name",
            rid=record_id,
        )
        return [
            {
                "edge_id": r["edge_id"],
                "edge_label": r["edge_label"],
                "fact_type": r["fact_type"] or "",
                "fact": r["fact"] or "",
                "confidence": r["confidence"] or "",
                "source_at": r["source_at"] or "",
                "source_record": r["source_record"] or "",
                "source_records": r["source_records"] or [],
                "stale": r["stale"] or False,
                "role": r["role"] or "",
                "from_id": r["from_id"],
                "from_name": r["from_name"] or "",
                "to_id": r["to_id"],
                "to_name": r["to_name"] or "",
            }
            for r in result
        ]


def get_edges_for_slot(
    from_id: str,
    edge_label: str,
    fact_type: str,
    to_id: str,
    include_stale: bool = False,
) -> list[dict]:
    """Get all fact-edges for a (from, label, type, to) slot."""
    with get_session() as session:
        where = (
            "WHERE elementId(a) = $from_id AND elementId(b) = $to_id "
            "AND type(r) = $label AND r.fact_type = $ft"
        )
        if not include_stale:
            where += " AND (r.stale IS NULL OR r.stale = false)"

        result = session.run(
            f"MATCH (a)-[r]->(b) {where} "
            "RETURN elementId(r) AS edge_id, r.fact AS fact, "
            "r.confidence AS confidence, r.source_at AS source_at, "
            "r.source_record AS source_record, r.source_records AS source_records, "
            "r.stale AS stale, r.role AS role",
            from_id=from_id,
            to_id=to_id,
            label=edge_label.upper(),
            ft=fact_type,
        )
        return [
            {
                "edge_id": r["edge_id"],
                "fact": r["fact"] or "",
                "confidence": r["confidence"] or "",
                "source_at": r["source_at"] or "",
                "source_record": r["source_record"] or "",
                "source_records": r["source_records"] or [],
                "stale": r["stale"] or False,
                "role": r["role"] or "",
            }
            for r in result
        ]
