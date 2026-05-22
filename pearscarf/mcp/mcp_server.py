"""MCP server — exposes PearScarf context queries via FastMCP over HTTP/SSE.

Tool surface (6 tools, dynamic primitives + bundles):

- get_schema: vocabulary introspection — entity_types, edge_labels, fact_types,
  source_types. Call once at task start to know the vocabulary.
- search: semantic similarity search across records (Qdrant + records join),
  with optional record_type / source / since filters.
- query_facts: parameterized graph query — subject / target / edge_label /
  fact_type / source_type / since / until / include_stale.
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

from pearscarf.config import MCP_HOST, MCP_HTTP_PORT, MCP_PORT
from pearscarf.mcp.auth import PearscarfAuthProvider
from pearscarf.query import context_query
from pearscarf.storage import graph, vectorstore
from pearscarf.storage.db import _get_conn, init_db

# Bearer-token auth against the `mcp_keys` table. Without a valid Bearer
# header, FastMCP returns 401 before any tool runs. Issue keys with
# `psc mcp-keys create <device>`; revoke with `psc mcp-keys revoke <id>`.
# The /health route declared with `@mcp.custom_route` bypasses this
# middleware.
mcp = FastMCP("PearScarf", auth=PearscarfAuthProvider())


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
        "fact_types, and source_types. Call this once at the start of a task "
        "so you know what to filter on in query_facts and query_records. "
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
        "(entity name or the literal '(Day)'), edge_label, fact_type, source_type, "
        "time range (since/until on source_at), and stale flag. Use after get_schema "
        "to know the vocabulary. Returns matching facts ordered by source_at descending. "
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
        "r.stale AS stale, r.valid_until AS valid_until, "
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
# Tool 7 — submit_record
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Submit a record into PearScarf. The record body follows the format "
        "described at the `pearscarf://format/record` resource — a markdown "
        "shape with `Title:` / `Id:` / `Date:` / scope-anchor / `## For humans` "
        "(brief prose) / `## For agents` (a YAML list of plain-language facts "
        "under `facts:`). Provide a non-empty `url` pointing to where the "
        "record is persisted (becomes `source_url` on every fact extracted). "
        "`op_area` is a record-level routing field: `reality` (default) sends "
        "the record through triage + extraction to the graph; `intent` "
        "persists the record but skips the graph (a dedicated submission "
        "surface for intents is coming separately). Returns `{record_id, "
        'status: "queued"}`. Fetch the format resource first if you don\'t '
        "already have the format in context."
    )
)
def submit_record(body: str, url: str, op_area: str = "reality") -> dict:
    """Submit a record into PearScarf via the records expert."""
    from pearscarf.records import RecordSubmissionError
    from pearscarf.registry import get_registry

    handler = get_registry().get_connect("record")
    if handler is None:
        return {
            "error": "RECORDS_NOT_INITIALIZED",
            "message": (
                "Records expert is not registered in this MCP process. "
                "Records init normally runs at MCP startup; if you see this "
                "error, check the MCP container logs for an init failure."
            ),
        }
    try:
        record_id = handler.ingest(body, url, op_area)
    except RecordSubmissionError as exc:
        return {"error": "INVALID_RECORD", "message": str(exc)}

    if record_id is None:
        return {"status": "duplicate", "message": "id already exists"}
    return {"record_id": record_id, "status": "queued"}


# ---------------------------------------------------------------------------
# Tool 8 — get_record_status
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Look up the lifecycle stage of a previously-submitted record. Returns "
        "one of: `received` (pearscarf has the body, processing not started), "
        "`evaluating` (pearscarf is deciding whether to extract), `extracting` "
        "(extractor is running), `indexed` (facts are in the graph and queryable), "
        "`rejected` (pearscarf chose not to extract), `needs_review` (pearscarf "
        "couldn't decide and queued the record for human review). Pair with "
        "`submit_record` to confirm a submission has reached `indexed`. Returns "
        "`{error: 'not_found'}` if no record exists with that id."
    )
)
def get_record_status(record_id: str) -> dict:
    """Return the user-facing stage of a record."""
    from pearscarf.storage import store

    record = store.get_record(record_id)
    if record is None:
        return {"error": "not_found", "record_id": record_id}

    classification = record.get("classification")
    indexed = bool(record.get("indexed"))

    if indexed:
        stage = "indexed"
    elif classification == store.NOISE:
        stage = "rejected"
    elif classification == store.UNCERTAIN:
        stage = "needs_review"
    elif classification == store.RELEVANT:
        stage = "extracting"
    elif classification == store.TRIAGING:
        stage = "evaluating"
    else:
        stage = "received"

    return {
        "record_id": record_id,
        "stage": stage,
        "classification": classification,
        "indexed": indexed,
        "created_at": _iso(record.get("created_at")),
    }


# ---------------------------------------------------------------------------
# Intent tools
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Submit an intent — a record describing a planned action / commitment. "
        "Intent records persist but skip extraction; they never reach the graph. "
        "Body is free-form prose; the canonical shape lives at the "
        "`pearscarf://format/intent` resource. Optional `parent_record_id` "
        "(another intent_id) makes this a sub-intent. Optional `intent_type` "
        "is the dispatch lifecycle — `'executor'` (default; runs once, "
        "completes) or `'coordinator'` (parent of children; wakes when "
        "children complete). Immutable after submit. Optional `owner` pins "
        "the intent to a specific agent identity (e.g. 'hex'); optional "
        "`owner_role` tags it by function (e.g. 'head-eng') so an orchestrator "
        "can match agents in that role. Optional `depends_on` is a list of "
        "other intent ids that must reach status='done' before this one is "
        "eligible for dispatch. Optional `runtime` selects which orchestrator "
        "adapter dispatches the intent (`'claude'` default, also `'codex'`, "
        "`'hermes'`, etc.); optional `runtime_config` is an opaque JSON "
        "object the orchestrator passes through to that adapter (for "
        "`'claude'`: e.g. `chrome_required`, `mcp_servers`, `model`, "
        "`prompt_role`). Optional `set_by` is the agent/operator submitting. "
        "Returns `{intent_id, status: 'todo'}`."
    )
)
def submit_intent(
    body: str,
    parent_record_id: str | None = None,
    intent_type: str = "executor",
    owner: str | None = None,
    owner_role: str | None = None,
    depends_on: list[str] | None = None,
    set_by: str | None = None,
    runtime: str = "claude",
    runtime_config: dict | None = None,
) -> dict:
    """Submit an intent record and create its initial sidecar state row."""
    from pearscarf.registry import get_registry
    from pearscarf.storage.intents import IntentError

    handler = get_registry().get_connect("record")
    if handler is None:
        return {
            "error": "RECORDS_NOT_INITIALIZED",
            "message": (
                "Records expert is not registered in this MCP process. "
                "Check the MCP container logs for an init failure."
            ),
        }
    try:
        intent_id = handler.ingest_intent(
            body=body,
            parent_record_id=parent_record_id,
            intent_type=intent_type,
            owner=owner,
            owner_role=owner_role,
            depends_on=depends_on,
            set_by=set_by,
            runtime=runtime,
            runtime_config=runtime_config,
        )
    except IntentError as exc:
        return {"error": "INVALID_INTENT", "message": str(exc)}
    return {"intent_id": intent_id, "status": "todo"}


@mcp.tool(
    description=(
        "List intents matching filters. `status` matches sidecar status "
        "(todo / in_progress / done / cancelled). `parent` filters direct "
        "children of a given intent id. `type` filters by intent_type "
        "(`'executor'` | `'coordinator'`). `owner` filters by specific agent "
        "identity. `owner_role` filters by the role tag (e.g. 'head-eng'). "
        "`runtime` filters by the orchestrator-adapter selector (e.g. "
        "`'claude'`, `'codex'`). `since` is an ISO timestamp on the intent's "
        "created_at. Returns body + state per match, newest first."
    )
)
def query_intents(
    status: str | None = None,
    parent: str | None = None,
    type: str | None = None,
    owner: str | None = None,
    owner_role: str | None = None,
    runtime: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> dict:
    """Filtered list of intents."""
    from pearscarf.storage import intents

    rows = intents.query_intents(
        status=status,
        parent_record_id=parent,
        intent_type=type,
        owner=owner,
        owner_role=owner_role,
        runtime=runtime,
        since=since,
        limit=limit,
    )
    return {
        "intents": [_normalize_intent(i) for i in rows],
        "count": len(rows),
    }


@mcp.tool(
    description=(
        "Fetch one intent by id. Returns body + status + parent_record_id + "
        "intent_type + audit fields. With `with_children=True`, includes direct "
        "children (depth 1)."
    )
)
def get_intent(id: str, with_children: bool = False) -> dict:
    """Single intent by id, optionally with direct children."""
    from pearscarf.storage import intents

    intent = intents.get_intent(id, with_children=with_children)
    if intent is None:
        return {"error": "not_found", "intent_id": id}
    result = _normalize_intent(intent)
    if with_children:
        result["children"] = [_normalize_intent(c) for c in intent.get("children", [])]
    return result


@mcp.tool(
    description=(
        "Recursive walk from a root intent. Returns the root with nested "
        "`children` lists at every level. Use for 'what's left under epic X' "
        "progress views."
    )
)
def get_intent_tree(root_id: str) -> dict:
    """Full sub-tree rooted at root_id."""
    from pearscarf.storage import intents

    root = intents.get_intent_tree(root_id)
    if root is None:
        return {"error": "not_found", "intent_id": root_id}
    return _normalize_intent_tree(root)


@mcp.tool(
    description=(
        "Set the status of an intent. `status` must be one of "
        "todo | in_progress | done | cancelled. `set_by` tags who flipped it "
        "(agent name, operator handle); stored on the sidecar audit field."
    )
)
def set_intent_status(id: str, status: str, set_by: str | None = None) -> dict:
    from pearscarf.storage import intents
    from pearscarf.storage.intents import IntentError

    try:
        intents.set_intent_status(id, status, set_by)
    except IntentError as exc:
        return {"error": "INVALID_INTENT", "message": str(exc)}
    return {"intent_id": id, "status": status}


@mcp.tool(
    description=(
        "Re-parent an intent. `parent_id=null` makes it top-level. Rejects "
        "re-parents that would form a cycle. `set_by` tags who reorganized."
    )
)
def set_intent_parent(id: str, parent_id: str | None, set_by: str | None = None) -> dict:
    from pearscarf.storage import intents
    from pearscarf.storage.intents import IntentError

    try:
        intents.set_intent_parent(id, parent_id, set_by)
    except IntentError as exc:
        return {"error": "INVALID_INTENT", "message": str(exc)}
    return {"intent_id": id, "parent_record_id": parent_id}


@mcp.tool(
    description=(
        "Set or clear the intent's `owner` (specific agent identity, e.g. 'hex'). "
        "Pass null to clear. `set_by` tags who made the change."
    )
)
def set_intent_owner(id: str, owner: str | None, set_by: str | None = None) -> dict:
    from pearscarf.storage import intents
    from pearscarf.storage.intents import IntentError

    try:
        intents.set_intent_owner(id, owner, set_by)
    except IntentError as exc:
        return {"error": "INVALID_INTENT", "message": str(exc)}
    return {"intent_id": id, "owner": owner}


@mcp.tool(
    description=(
        "Set or clear the intent's `owner_role` (function tag, e.g. 'head-eng'). "
        "Pass null to clear. `set_by` tags who made the change."
    )
)
def set_intent_owner_role(id: str, owner_role: str | None, set_by: str | None = None) -> dict:
    from pearscarf.storage import intents
    from pearscarf.storage.intents import IntentError

    try:
        intents.set_intent_owner_role(id, owner_role, set_by)
    except IntentError as exc:
        return {"error": "INVALID_INTENT", "message": str(exc)}
    return {"intent_id": id, "owner_role": owner_role}


@mcp.tool(
    description=(
        "Replace the intent's `depends_on` array — the list of intent ids that "
        "must reach status='done' before this intent is eligible for dispatch. "
        "Pass `[]` to clear all deps. Rejects missing referent intents and "
        "cycles. `set_by` tags who made the change."
    )
)
def set_intent_dependencies(id: str, depends_on: list[str], set_by: str | None = None) -> dict:
    from pearscarf.storage import intents
    from pearscarf.storage.intents import IntentError

    try:
        intents.set_intent_dependencies(id, depends_on, set_by)
    except IntentError as exc:
        return {"error": "INVALID_INTENT", "message": str(exc)}
    return {"intent_id": id, "depends_on": depends_on}


def _normalize_intent(intent: dict) -> dict:
    """Shape an intent record for MCP responses — ISO timestamps + stable keys."""
    return {
        "intent_id": intent["id"],
        "body": intent.get("body") or "",
        "status": intent.get("status"),
        "parent_record_id": intent.get("parent_record_id"),
        "intent_type": intent.get("intent_type"),
        "owner": intent.get("owner"),
        "owner_role": intent.get("owner_role"),
        "depends_on": list(intent.get("depends_on") or []),
        "runtime": intent.get("runtime"),
        "runtime_config": intent.get("runtime_config") or {},
        "source": intent.get("source") or "",
        "created_at": _iso(intent.get("created_at")),
        "set_at": _iso(intent.get("set_at")),
        "set_by": intent.get("set_by") or "",
    }


def _normalize_intent_tree(node: dict) -> dict:
    """Recursively normalize a tree of intents."""
    out = _normalize_intent(node)
    out["children"] = [_normalize_intent_tree(c) for c in node.get("children", [])]
    return out


# ---------------------------------------------------------------------------
# Resource — records format spec
# ---------------------------------------------------------------------------


@mcp.resource(
    uri="pearscarf://format/record",
    name="records format spec",
    description=(
        "PearScarf records format spec — describes the body shape clients use to "
        "submit records via the records expert (Title / Id / Date / anchor / "
        "## For humans / ## For agents) and the author discipline. Fetch this "
        "before submitting a record if you don't already have the format in context."
    ),
    mime_type="text/markdown",
)
def records_format_spec() -> str:
    """Serve the records format spec from the records expert's knowledge dir."""
    from pearscarf.registry import get_registry

    expert = get_registry().get_by_name("records")
    if expert is None or expert.knowledge_dir is None:
        raise FileNotFoundError("records expert not registered")
    return (expert.knowledge_dir / "format.md").read_text()


@mcp.resource(
    uri="pearscarf://format/intent",
    name="intent format spec",
    description=(
        "PearScarf intent format spec — describes the body shape clients use to "
        "submit intents via `submit_intent`, what / who / why / acceptance "
        "framing, and the author discipline that separates committed plans "
        "from exploratory thoughts. Fetch before submitting an intent."
    ),
    mime_type="text/markdown",
)
def intent_format_spec() -> str:
    """Serve the intent format spec from pearscarf/knowledge/intents/format.md."""
    from pathlib import Path

    import pearscarf

    path = Path(pearscarf.__file__).parent / "knowledge" / "intents" / "format.md"
    return path.read_text()


# ---------------------------------------------------------------------------
# Server runner
# ---------------------------------------------------------------------------


class MCPServer:
    """Background thread running the FastMCP server with dual transports (SSE + HTTP)."""

    def __init__(self) -> None:
        self._sse_thread: threading.Thread | None = None
        self._http_thread: threading.Thread | None = None

    def _run_sse(self) -> None:
        init_db()
        mcp.run(
            transport="sse",
            host=MCP_HOST,
            port=MCP_PORT,
        )

    def _run_http(self) -> None:
        init_db()
        mcp.run(
            transport="streamable-http",
            host=MCP_HOST,
            port=MCP_HTTP_PORT,
        )

    def start(self) -> None:
        """Start both SSE and HTTP MCP servers in background daemon threads."""
        self._sse_thread = threading.Thread(
            target=self._run_sse, name="mcp-server-sse", daemon=True
        )
        self._http_thread = threading.Thread(
            target=self._run_http, name="mcp-server-http", daemon=True
        )
        self._sse_thread.start()
        self._http_thread.start()

    def stop(self) -> None:
        # FastMCP doesn't expose a clean shutdown — daemon threads die with process
        pass

    def run_foreground(self) -> None:
        """Run both MCP servers in the foreground (blocking) — HTTP in main thread, SSE in background."""
        init_db()
        print(
            f"MCP server starting on {MCP_HOST}:{MCP_PORT} (SSE) and {MCP_HOST}:{MCP_HTTP_PORT} (HTTP)"
        )
        # Start SSE in background thread
        sse_thread = threading.Thread(target=self._run_sse, name="mcp-server-sse", daemon=False)
        sse_thread.start()
        # Run HTTP in main thread (blocking)
        self._run_http()
