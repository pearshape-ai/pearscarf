# Context Query — Data Access Layer

`pearscarf/query/context_query.py` is the single read-only data access layer for all context queries. Both the Assistant's graph query tools (`pearscarf/graph_query_tools.py`) and the external MCP server call through it. No other module should call `graph.py` or `store.py` read functions directly for context-building purposes.

## Why it exists

A single source of truth for "how do I get context from PearScarf." Internal tools and the external MCP surface read through the same functions, so results stay consistent and logic is not duplicated per consumer.

## Design principles

- **Read-only** — never writes to any storage
- **Storage-agnostic** — callers don't know whether data comes from Neo4j, Postgres, or Qdrant
- **Two consumers** — `graph_query_tools.py` (Assistant-facing tools) and `mcp_server.py` (external clients via MCP)

## Functions

### `find_entity(name, entity_type=None) -> list[dict]`

Search for entities by name, email, or domain. Returns `[{id, name, type, metadata}]`.

**Storage:** Neo4j

---

### `get_facts(entity_id, edge_label=None, fact_type=None, include_stale=False, since=None) -> list[dict]`

Get fact-edges for an entity with optional filters.

- `edge_label`: AFFILIATED, ASSERTED, or TRANSITIONED
- `fact_type`: any valid sub-type (employee, commitment, status_change, etc.)
- `since`: ISO datetime, only facts where `source_at >= since`

**Storage:** Neo4j

---

### `get_connections(entity_id, max_depth=1, include_stale=False, edge_labels=None) -> dict`

Traverse fact-edges from an entity. Returns `{nodes, edges, source_records}`.

**Storage:** Neo4j

---

### `get_facts_for_day(date) -> list[dict]`

Get single-entity facts anchored to a Day node.

**Storage:** Neo4j

---

### `get_path(entity_id_a, entity_id_b) -> dict`

Shortest path between two entities via current fact-edges. Returns `{path, direct_facts}`.

**Storage:** Neo4j

---

### `get_conflicts(entity_id=None) -> list[dict]`

Find AFFILIATED slots with multiple current (non-stale) edges. Optionally scoped to one entity.

**Storage:** Neo4j

---

### `get_communications(entity_id, since=None) -> list[dict]`

Get records where the entity appears as sender or recipient. Resolves entity to name/email, then queries Postgres records table by metadata.

**Storage:** Neo4j (entity resolution) + Postgres (records table metadata)

---

### `vector_search(query, n_results=5) -> list[dict]`

Semantic similarity search across stored records.

**Storage:** Qdrant
