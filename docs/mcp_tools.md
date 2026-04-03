# MCP Tools Reference

PearScarf exposes a read-only query surface via MCP over HTTP/SSE. Any MCP-compatible agent framework connects once and queries for context.

## Authentication

Create an API key:
```bash
psc mcp keys create --name "my-agent"
# Key: psk_abc123...
# Save this key — it will not be shown again.
```

Every request must include:
```
Authorization: Bearer psk_abc123...
```

## Base URL and Health

Default: `http://localhost:8090`

Health check (no auth required):
```
GET /health → {"status": "ok", "version": "1.15.6"}
```

## Error Shapes

All tools return consistent error shapes:

```json
{"error": "not_found", "name": "Unknown Person"}
{"error": "invalid_format", "valid_values": ["chronological", "clustered"]}
```

## Entity Resolution

Most tools accept `entity_name` as a surface form string. Entities are resolved internally — the tool searches PearScarf's graph and uses the top match. When names are ambiguous, call `find_entity` first to inspect candidates.

---

## Primitive Tools

### `find_entity`

Resolve a name to a canonical entity.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Surface form to search |
| `entity_type` | string | no | Filter: person, company, project, event |

Returns: `{"entities": [{id, name, type, metadata}]}`

Use when: confirming PearScarf knows an entity, or disambiguating a name.

---

### `get_facts`

Get facts about an entity. The workhorse query.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `entity_name` | string | yes | Surface form, resolved internally |
| `edge_label` | string | no | AFFILIATED, ASSERTED, or TRANSITIONED |
| `fact_type` | string | no | Sub-type filter (employee, commitment, etc.) |
| `include_stale` | boolean | no | Include superseded facts. Default false. |
| `since` | string | no | ISO datetime. Only facts after this time. |

Returns: `{"entity": {...}, "facts": [<canonical fact objects>], "count": N}`

Use when: querying facts about an entity, optionally filtered.

---

### `get_connections`

Get entities directly connected via fact-edges.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `entity_name` | string | yes | Surface form, resolved internally |
| `edge_label` | string | no | Filter to one edge label |
| `include_stale` | boolean | no | Include stale edges. Default false. |

Returns: `{"entity": {...}, "connections": [{id, name, type}], "edges": [...], "count": N}`

---

### `get_relationship`

Find how two entities are connected.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `entity_a` | string | yes | First entity name |
| `entity_b` | string | yes | Second entity name |

Returns: `{"entity_a": {...}, "entity_b": {...}, "direct_facts": [...], "path": [...]}`

Empty path/direct_facts is valid — means no connection found.

---

### `get_conflicts`

Find AFFILIATED slots with multiple current conflicting values.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `entity_name` | string | no | Scope to one entity. Omit for global. |

Returns: `{"conflicts": [{entity_name, edge_label, fact_type, fact_a, fact_b, ...}], "count": N}`

---

## Convenience Tools

### `get_entity_context`

Full picture: all facts + connections.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `entity_name` | string | yes | Surface form, resolved internally |
| `format` | string | no | `chronological` (default) or `clustered` |
| `include_stale` | boolean | no | Default false |

Returns: `{"entity": {...}, "facts": [...] or {...}, "connections": [...], "count": N}`

Use when: acting on behalf of or about an entity — need the full picture.

---

### `get_current_state`

Current affiliations only (AFFILIATED, non-stale).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `entity_name` | string | yes | Surface form, resolved internally |

Returns: `{"entity": {...}, "affiliations": [...], "count": N}`

Use when: need to know who someone works for or what projects they belong to.

---

### `get_open_commitments`

Pending commitments with deadlines.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `entity_name` | string | no | Scope to entity. Omit for global. |
| `before_date` | string | no | ISO date. Only commitments due before this date. |
| `format` | string | no | `chronological` (default) or `clustered` |

Returns: `{"commitments": [...], "count": N}`

Only includes commitments with `valid_until` set.

---

### `get_open_blockers`

Current blockers without subsequent resolution.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `entity_name` | string | no | Scope to entity. |

Returns: `{"blockers": [...], "count": N}`

---

### `get_recent_activity`

Recent transitions, references, and communications.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `entity_name` | string | yes | Surface form, resolved internally |
| `since` | string | no | ISO datetime. Default: 7 days ago. |
| `format` | string | no | `chronological` (default) or `clustered` |

Returns: `{"entity": {...}, "activity": [{type: "fact"|"communication", ...}], "count": N, "since": "..."}`

Use when: catching up on a deal, project, or person.

---

## Canonical Fact Object

Every fact returned by any tool follows this shape:

```json
{
  "edge_label": "ASSERTED",
  "fact_type": "commitment",
  "fact": "Marcus Webb committed to deliver the contract markup by March 16",
  "confidence": "stated",
  "source_at": "2026-03-14T10:22:00Z",
  "source_record": "email_007",
  "stale": false,
  "other_name": "Meridian Deal"
}
```
