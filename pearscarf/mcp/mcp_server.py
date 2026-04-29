"""MCP server — exposes PearScarf context queries via FastMCP over HTTP/SSE.

Tool surface (6 tools, dynamic primitives + bundles):

- get_schema: vocabulary introspection — entity_types, edge_labels, fact_types,
  source_types, op_areas. Call once at task start to know the vocabulary.
- search: semantic similarity search across records (Qdrant + records join),
  with optional record_type / source / since filters.
- query_facts: parameterized graph query — subject / target / edge_label /
  fact_type / op_area / source_type / since / until / include_stale.
- query_records: parameterized records query — type / source / expert /
  classification / since / until / metadata field matchers.
- get_entity_context: high-value bundle — facts + connections + recent records
  for an entity. The "tell me everything about X" tool.
- get_relationship: high-value bundle — direct facts + shortest path between
  two entities.

Earlier narrow tools (find_entity, get_facts, get_current_state,
get_open_blockers, get_open_commitments, get_recent_activity, get_conflicts,
get_connections) are expressible via the dynamic primitives plus schema
knowledge — agents call get_schema once and then compose query_facts /
query_records calls.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime

from fastmcp import FastMCP

from pearscarf.config import MCP_HOST, MCP_PORT
from pearscarf.query import context_query
from pearscarf.storage import graph, vectorstore
from pearscarf.storage.db import _get_conn, init_db

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
# Helpers
# ---------------------------------------------------------------------------


def _resolve_entity(entity_name: str) -> tuple[dict | None, dict | None]:
    """Resolve a name to an entity. Returns (entity_dict, error_dict)."""
    matches = context_query.find_entity(entity_name)
    if not matches:
        return None, {"error": "not_found", "name": entity_name}
    return matches[0], None


_VALID_KEY = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _iso(dt: datetime | None) -> str:
    """Safely ISO-format a datetime that may be None."""
    return dt.isoformat() if dt is not None else ""


# ---------------------------------------------------------------------------
# Tool 1 — get_schema
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Return this deployment's vocabulary — entity types, edge labels, "
        "fact_types, source_types, and op_areas. Call this once at the start "
        "of a task so you know what to filter on in query_facts and query_records. "
        "The fact_types map is keyed by edge_label and lists the canonical "
        "fact_types each edge accepts (deployment-vocab additions included)."
    )
)
def get_schema() -> dict:
    """Vocabulary introspection."""
    init_db()

    entity_types = sorted(graph._LABELS.keys())
    edge_labels = sorted(graph.FACT_CATEGORIES.keys())
    fact_types = {label: sorted(types) for label, types in graph.FACT_CATEGORIES.items()}

    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT type FROM records WHERE type IS NOT NULL ORDER BY type"
        ).fetchall()
        source_types = [dict(r)["type"] for r in rows]

    return {
        "entity_types": entity_types,
        "edge_labels": edge_labels,
        "fact_types": fact_types,
        "source_types": source_types,
        "op_areas": ["reality", "intention"],
    }


# ---------------------------------------------------------------------------
# Tool 2 — search
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Semantic search over records (Qdrant embedding similarity + Postgres join). "
        "Takes a natural-language query plus optional filters (record_type, source, since). "
        "Returns top-N records with relevance scores and key metadata. "
        "Use to find records about a topic when you don't know the exact entity names — "
        "e.g. 'records about anchored extensibility' or 'past messaging on deployment vocab'."
    )
)
def search(
    query: str,
    record_type: str | None = None,
    source: str | None = None,
    since: str | None = None,
    n: int = 10,
) -> dict:
    """Semantic search across records."""
    init_db()

    fetch_n = n * 4 if (record_type or source or since) else n
    hits = vectorstore.query(query, n_results=fetch_n)
    if not hits:
        return {"query": query, "results": [], "count": 0}

    record_ids = [h["id"] for h in hits if h.get("id")]
    if not record_ids:
        return {"query": query, "results": [], "count": 0}

    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, type, source, classification, created_at, expert_name, metadata "
            "FROM records WHERE id = ANY(%s)",
            (record_ids,),
        ).fetchall()
    record_map = {dict(r)["id"]: dict(r) for r in rows}

    results = []
    for hit in hits:
        rid = hit.get("id")
        rec = record_map.get(rid)
        if not rec:
            continue

        if record_type and rec.get("type") != record_type:
            continue
        if source and source.lower() not in (rec.get("source") or "").lower():
            continue
        if since and _iso(rec.get("created_at")) < since:
            continue

        results.append(
            {
                "record_id": rid,
                "type": rec.get("type") or "",
                "source": rec.get("source") or "",
                "expert": rec.get("expert_name") or "",
                "classification": rec.get("classification") or "",
                "created_at": _iso(rec.get("created_at")),
                "metadata": rec.get("metadata") or {},
                "snippet": (hit.get("content") or "")[:300],
                "score": hit.get("score") or 0.0,
            }
        )
        if len(results) >= n:
            break

    return {"query": query, "results": results, "count": len(results)}


# ---------------------------------------------------------------------------
# Tool 3 — query_facts
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Parameterized graph query. Filter facts by subject (entity name), target "
        "(entity name or the literal '(Day)'), edge_label, fact_type, op_area "
        "('reality' or 'intention'), source_type, time range (since/until on source_at), "
        "and stale flag. Use after get_schema to know the vocabulary. Returns matching "
        "facts ordered by source_at descending. "
        "Examples: open blockers on PearScarf → subject='PearScarf', edge_label='ASSERTED', "
        "fact_type='blocker'. Recent shipping events → edge_label='TRANSITIONED', "
        "fact_type='feature_shipped', since='2026-04-01T00:00:00Z'."
    )
)
def query_facts(
    subject: str | None = None,
    target: str | None = None,
    edge_label: str | None = None,
    fact_type: str | None = None,
    op_area: str | None = None,
    source_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    include_stale: bool = False,
    limit: int = 50,
) -> dict:
    """Parameterized graph query. Returns facts matching all provided filters."""
    init_db()

    where_parts = ["r.fact IS NOT NULL"]
    params: dict = {}

    if subject:
        where_parts.append("a.name = $subject_name")
        params["subject_name"] = subject

    if target:
        if target == "(Day)":
            where_parts.append("'Day' IN labels(b)")
        else:
            where_parts.append("(b.name = $target_name OR b.date = $target_name)")
            params["target_name"] = target

    if edge_label:
        where_parts.append("type(r) = $edge_label")
        params["edge_label"] = edge_label

    if fact_type:
        where_parts.append("r.fact_type = $fact_type")
        params["fact_type"] = fact_type

    if op_area:
        where_parts.append("r.op_area = $op_area")
        params["op_area"] = op_area

    if source_type:
        where_parts.append("r.source_type = $source_type")
        params["source_type"] = source_type

    if since:
        where_parts.append("r.source_at >= $since")
        params["since"] = since

    if until:
        where_parts.append("r.source_at <= $until")
        params["until"] = until

    if not include_stale:
        where_parts.append("(r.stale IS NULL OR r.stale = false)")

    where_clause = " AND ".join(where_parts)
    params["limit"] = limit

    cypher = (
        f"MATCH (a)-[r]->(b) WHERE {where_clause} "
        "RETURN elementId(r) AS rid, type(r) AS edge_label, "
        "r.fact_type AS fact_type, r.fact AS fact, "
        "r.confidence AS confidence, r.source_record AS source_record, "
        "r.source_type AS source_type, r.source_at AS source_at, "
        "r.op_area AS op_area, r.stale AS stale, r.valid_until AS valid_until, "
        "elementId(a) AS subject_id, a.name AS subject_name, labels(a) AS subject_labels, "
        "elementId(b) AS target_id, b.name AS target_name, b.date AS target_date, "
        "labels(b) AS target_labels "
        "ORDER BY r.source_at DESC LIMIT $limit"
    )

    with graph.get_session() as session:
        rows = session.run(cypher, **params).data()

    facts = []
    for r in rows:
        target_labels = r.get("target_labels") or []
        if "Day" in target_labels:
            target_display = r.get("target_date") or "?"
        else:
            target_display = r.get("target_name") or "?"
        facts.append(
            {
                "id": r["rid"],
                "edge_label": r.get("edge_label"),
                "fact_type": r.get("fact_type") or "",
                "fact": r.get("fact"),
                "confidence": r.get("confidence") or "",
                "op_area": r.get("op_area") or "",
                "source_at": r.get("source_at") or "",
                "source_record": r.get("source_record") or "",
                "source_type": r.get("source_type") or "",
                "stale": r.get("stale") or False,
                "valid_until": r.get("valid_until"),
                "subject": {"id": r.get("subject_id"), "name": r.get("subject_name")},
                "target": {"id": r.get("target_id"), "name": target_display},
            }
        )

    filters_applied = {
        k: v
        for k, v in {
            "subject": subject,
            "target": target,
            "edge_label": edge_label,
            "fact_type": fact_type,
            "op_area": op_area,
            "source_type": source_type,
            "since": since,
            "until": until,
            "include_stale": include_stale or None,
        }.items()
        if v is not None
    }
    return {"facts": facts, "count": len(facts), "filters_applied": filters_applied}


# ---------------------------------------------------------------------------
# Tool 4 — query_records
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Parameterized records query against Postgres. Filter by record type, source, "
        "expert, classification, time range (created_at), and metadata field matchers "
        "(metadata is a dict — each {key: value} adds a `metadata->>'key' = 'value'` "
        "match). Returns record summaries with snippets. Use to find raw source records "
        "(Linear issues, emails, spreadsheet rows) by structured criteria — e.g. all "
        "Linear issues marked Done since last Tuesday, or all email records from a "
        "specific sender."
    )
)
def query_records(
    type: str | None = None,
    source: str | None = None,
    expert: str | None = None,
    classification: str | None = None,
    since: str | None = None,
    until: str | None = None,
    metadata: dict | None = None,
    limit: int = 50,
) -> dict:
    """Parameterized records query."""
    init_db()
    where_parts: list[str] = []
    params: list = []

    if type:
        where_parts.append("type = %s")
        params.append(type)
    if source:
        where_parts.append("source ILIKE %s")
        params.append(f"%{source}%")
    if expert:
        where_parts.append("expert_name = %s")
        params.append(expert)
    if classification:
        where_parts.append("classification = %s")
        params.append(classification)
    if since:
        where_parts.append("created_at >= %s")
        params.append(since)
    if until:
        where_parts.append("created_at <= %s")
        params.append(until)
    if metadata:
        for k, v in metadata.items():
            if not _VALID_KEY.match(k):
                continue
            where_parts.append("metadata->>%s = %s")
            params.append(k)
            params.append(str(v))

    where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    params.append(limit)

    sql = (
        "SELECT id, type, source, classification, created_at, expert_name, "
        "expert_version, metadata, LEFT(content, 300) AS snippet "
        f"FROM records{where_clause} "
        "ORDER BY created_at DESC LIMIT %s"
    )

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    records = []
    for r in rows:
        d = dict(r)
        records.append(
            {
                "record_id": d["id"],
                "type": d.get("type") or "",
                "source": d.get("source") or "",
                "classification": d.get("classification") or "",
                "expert": d.get("expert_name") or "",
                "expert_version": d.get("expert_version") or "",
                "created_at": _iso(d.get("created_at")),
                "metadata": d.get("metadata") or {},
                "snippet": d.get("snippet") or "",
            }
        )

    return {"records": records, "count": len(records)}


# ---------------------------------------------------------------------------
# Tool 5 — get_entity_context
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "High-value bundle: given an entity name, return its facts + direct connections "
        "+ recent source records that produced those facts. The 'tell me everything "
        "about X' tool. Use when starting work on an entity and want a single shot of "
        "context. Format 'chronological' returns facts sorted by source_at; "
        "'clustered' groups them by edge_label."
    )
)
def get_entity_context(
    entity_name: str,
    format: str = "chronological",
    include_stale: bool = False,
) -> dict:
    """Full entity context: facts + connections + recent records."""
    if format not in ("chronological", "clustered"):
        return {"error": "invalid_format", "valid_values": ["chronological", "clustered"]}

    entity, err = _resolve_entity(entity_name)
    if err:
        return err
    assert entity is not None

    facts = context_query.get_facts(entity["id"], include_stale=include_stale)
    conns_result = context_query.get_connections(
        entity["id"], max_depth=1, include_stale=include_stale
    )
    connections = [n for n in conns_result.get("nodes", []) if n.get("type") != "day"]

    record_ids = list({f.get("source_record") for f in facts if f.get("source_record")})
    related_records: list[dict] = []
    if record_ids:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT id, type, source, created_at, LEFT(content, 200) AS snippet "
                "FROM records WHERE id = ANY(%s) ORDER BY created_at DESC LIMIT 20",
                (record_ids,),
            ).fetchall()
        for r in rows:
            d = dict(r)
            related_records.append(
                {
                    "record_id": d["id"],
                    "type": d.get("type") or "",
                    "source": d.get("source") or "",
                    "created_at": _iso(d.get("created_at")),
                    "snippet": d.get("snippet") or "",
                }
            )

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
            "related_records": related_records,
            "count": len(facts),
        }

    clustered: dict[str, list] = {}
    for f in facts:
        label = f.get("edge_label", "OTHER")
        clustered.setdefault(label, []).append(f)
    return {
        "entity": entity_info,
        "facts": clustered,
        "connections": connections,
        "related_records": related_records,
        "count": len(facts),
    }


# ---------------------------------------------------------------------------
# Tool 6 — get_relationship
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "High-value bundle: given two entity names, return how they connect — direct "
        "facts between them, plus the shortest path through the graph if no direct "
        "connection exists. Use before drafting a message or making a decision involving "
        "two parties."
    )
)
def get_relationship(entity_a: str, entity_b: str) -> dict:
    """Find how two entities connect."""
    ent_a, err_a = _resolve_entity(entity_a)
    if err_a:
        return err_a
    ent_b, err_b = _resolve_entity(entity_b)
    if err_b:
        return err_b
    assert ent_a is not None and ent_b is not None

    result = context_query.get_path(ent_a["id"], ent_b["id"])
    return {
        "entity_a": {"id": ent_a["id"], "name": ent_a["name"], "type": ent_a["type"]},
        "entity_b": {"id": ent_b["id"], "name": ent_b["name"], "type": ent_b["type"]},
        "direct_facts": result.get("direct_facts", []),
        "path": result.get("path", []),
    }


# ---------------------------------------------------------------------------
# Server runner
# ---------------------------------------------------------------------------


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
        self._thread = threading.Thread(target=self._run, name="mcp-server", daemon=True)
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
