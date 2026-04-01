# Query Surface

PearScarf exposes a read-only query surface via MCP. Agents call these tools to get structured context without reconstructing it from raw records. Writes happen through expert agents only — never through MCP.

---

## Design principles

- **Read-only** — all tools return context, none write to the graph
- **Temporal filters by default** — every query returns `stale=false`, ordered by `source_at` descending
- **Entity resolution on input** — tool inputs are surface-form names; PearScarf resolves them to canonical nodes internally
- **Structured for agents** — responses are shaped for direct agent consumption, not raw graph data
- **Source links included** — every fact carries a `source_url` linking back to the original record where available

---

## Two layers

**Primitive layer** — direct graph queries. Composable, no semantic assumptions. Use when you need something specific.

**Convenience layer** — common patterns pre-composed into one call. Use to minimise agent cycles for the most frequent tasks.

---

## Output formats

Two formats available on tools that return collections of facts, via a `format` parameter:

**`chronological` (default)** — flat array of fact objects ordered by `source_at` ascending. No clustering. Use when an agent needs to reason over what happened and in what order.

**`clustered`** — facts grouped by edge label. Same properties on every fact. Use when an agent needs to understand the current state of an entity grouped by relationship type.

Anything processed on top of these formats — narrative generation, summarisation, prioritisation — is the consuming agent's responsibility.

---

## Canonical fact object

Every tool response contains fact objects in this shape:

```json
{
  "edge_label": "ASSERTED",
  "fact_type": "commitment",
  "fact": "Marcus Webb committed to deliver the Meridian contract markup by end of day March 16",
  "confidence": "stated",
  "source_at": "2026-03-14T10:22:00Z",
  "recorded_at": "2026-03-30T08:01:45Z",
  "valid_until": "2026-03-16",
  "source_record": "email_007",
  "source_url": "https://mail.google.com/...",
  "stale": false,
  "replaced_by": null,
  "from_entity": { "name": "Marcus Webb", "type": "Person" },
  "to_entity": { "name": "Meridian Deal", "type": "Project" }
}
```

`source_url` is null when the source record type has no linkable URL. `valid_until` is null when the fact has no explicit deadline. `to_entity` is null when the fact is anchored to a Day node.

---

## Primitive layer

### `pearscarf.find_entity`

Resolve a surface form to a canonical entity node.

```
Input:  name (string)

Output: entity { id, name, type, metadata }
        aliases: [surface_form, ...]
```

**Use when:** an agent has a name and needs to confirm PearScarf knows this entity before querying further. Useful as a pre-flight check before calling other tools.

---

### `pearscarf.get_facts`

Filtered fact query. The universal primitive — everything else is built on this.

```
Input:  entity        (string)
        edge_label?   ("AFFILIATED" | "ASSERTED" | "TRANSITIONED")
        fact_type?    (string — any valid fact_type for the given edge_label)
        since?        (ISO date — filter by source_at)
        include_stale? (bool, default false)
        format?       ("chronological" | "clustered", default "chronological")

Output: facts: [fact object, ...]
```

**Use when:** you need a specific slice of what PearScarf knows — a particular fact type, a date range, or stale history. Examples:

```python
# All blockers for a project
get_facts("Meridian API Integration", edge_label="ASSERTED", fact_type="blocker")

# All commitments for a person
get_facts("Marcus Webb", edge_label="ASSERTED", fact_type="commitment")

# Full transition history for a deal
get_facts("Meridian Deal", edge_label="TRANSITIONED", include_stale=True)

# Everything asserted in the last 14 days
get_facts("James Whitfield", edge_label="ASSERTED", since="2026-03-17")
```

---

### `pearscarf.get_connections`

All entities directly connected to this entity, with the edge labels between them.

```
Input:  entity (string)

Output: connections: [{ entity_name, entity_type, edge_label, fact_type }]
```

**Use when:** an agent needs to understand who or what an entity is connected to, without fetching all the facts. Useful for mapping the shape of a relationship before going deeper.

---

### `pearscarf.get_relationship`

How two entities are connected in the graph.

```
Input:  entity_a (string)
        entity_b (string)

Output: path: [{ entity, edge_label, fact_type, fact, direction }]
        direct_facts: [fact object, ...]
```

**Use when:** understanding the relationship between two parties before drafting a message or making a decision. Returns both the shortest path through the graph and any direct facts between them.

---

### `pearscarf.get_conflicts`

Facts currently flagged as ambiguous — two current (non-stale) facts for the same (entity, edge label, fact_type).

```
Input:  entity? (string, optional)

Output: conflicts: [{ entity, edge_label, fact_type, fact_a, fact_b, source_at_a, source_at_b }]
```

**Use when:** the verification agent or a human is reviewing graph health. Conflicts arise when two facts with equal `source_at` exist for the same slot — neither can be automatically staled.

---

## Convenience layer

### `pearscarf.get_entity_context`

Everything PearScarf knows about an entity in one call — current facts, connections, and recent activity.

```
Input:  entity        (string)
        since?        (ISO date — recency window for activity, default: 7 days ago)
        include_stale? (bool, default false)
        format?       ("chronological" | "clustered", default "chronological")

Output: entity         { id, name, type, metadata }
        current_facts  [fact object, ...]     — stale=false
        connections    [{ entity_name, entity_type, edge_label, fact_type }]
        recent_activity [fact object, ...]    — TRANSITIONED + ASSERTED[reference], since window
```

**Use when:** an agent needs a full picture of a person, company, or project before acting. This is the right starting point for most tasks — one call, no chaining required.

Equivalent to calling `get_facts` + `get_connections` + `get_facts(TRANSITIONED, since=...)` separately, but in one round trip.

---

## Usage examples

### Monday morning briefing

> "What's the status of the Meridian deal and what's outstanding?"

```python
pearscarf.get_entity_context("Meridian Deal")
```

One call. Returns current affiliations, all open assertions, recent transitions, and connected entities.

---

### Drafting a follow-up email

> "Draft a follow-up to James Whitfield about the contract."

```python
pearscarf.get_entity_context("James Whitfield")
pearscarf.get_relationship("James Whitfield", "Meridian Deal")
```

Two calls — full context on James plus how he connects to the deal.

---

### All open commitments for a project

```python
pearscarf.get_facts("Meridian Deal", edge_label="ASSERTED", fact_type="commitment")
```

---

### What's currently blocked

```python
pearscarf.get_facts("Meridian API Integration", edge_label="ASSERTED", fact_type="blocker")
```

---

### Reviewing graph health

```python
pearscarf.get_conflicts()
```

---

## Authentication

MCP auth is scoped to the deployment. Agents within a deployment get access automatically. External agents feeding new records back into PearScarf do so through the ingest pipeline, not through MCP write tools.

---

## Related docs

- [Data Model](data-model.md) — entities, edge labels, fact schema, confidence values, bi-temporal model
- [Eval Metrics](eval-metrics.md) — how extraction quality is measured
- [Roadmap](roadmap.md) — verification agent, expert encapsulation