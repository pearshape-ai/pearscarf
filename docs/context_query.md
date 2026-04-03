# Context Query — Data Access Layer

`pearscarf/context_query.py` is the single read-only data access layer for all context queries. Both the internal retriever agent and the external MCP server call through it. No other module should call `graph.py` or `store.py` read functions directly for context-building purposes.

## Why it exists

Before `context_query.py`, the retriever called `graph.py` directly and the MCP server would have needed its own parallel query path. Two diverging retrieval surfaces means inconsistent results and duplicated logic. `context_query.py` is the single source of truth for "how do I get context from PearScarf."

## Design principles

- **Read-only** — never writes to any storage
- **Storage-agnostic** — callers don't know whether data comes from Neo4j, Postgres, or Qdrant
- **Two consumers** — `retriever.py` (internal agents) and `mcp_server.py` (external agents via MCP)

## Functions

### `find_entity(name, entity_type=None) -> list[dict]`

Search for entities by name, email, or domain. Returns `[{id, name, type, metadata}]`.

**Storage:** Neo4j

---

### `get_facts(entity_id, edge_label=None, fact_type=None, include_stale=False, since=None) -> list[dict]`

Get fact-edges for an entity with optional filters. Post-filters in Python after fetching from graph.

- `edge_label`: AFFILIATED, ASSERTED, or TRANSITIONED
- `fact_type`: any valid sub-type (employee, commitment, status_change, etc.)
- `since`: ISO datetime, only facts where `source_at >= since`

Returns canonical fact objects.

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

Get emails where the entity appears as sender or recipient. Resolves entity to name/email, then queries Postgres.

**Storage:** Neo4j (entity resolution) + Postgres (emails table)

---

### `vector_search(query, n_results=5) -> list[dict]`

Semantic similarity search across stored records.

**Storage:** Qdrant
