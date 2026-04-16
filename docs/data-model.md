# Data Model

PearScarf builds a reality-aligned knowledge graph from the records your PearScarf expert agents observe. This document defines every concept in that graph — precisely, with examples.

---

## Entities

Entities are durable real-world things. They are the nodes of the graph.

| Type | Meaning | Examples |
|---|---|---|
| `Person` | A human individual | James Whitfield, Priya Nair |
| `Company` | An organization | Meridian Systems, Pear Ventures |
| `Project` | A tracked initiative or deal | Meridian Deal, Series A Prep |
| `Event` | A discrete occurrence | Meridian Demo, Board Meeting |

**Rules:**
- No version nodes. "API 1.2.0" is not an entity — it belongs in fact text.
- No sub-entities for qualifiers. Versions, stages, and modifiers are properties of facts, not separate nodes.
- Entities are merged on canonical name + metadata (email, domain). Aliases are tracked separately via IDENTIFIED_AS self-edges.

---

## Facts

A fact is a claim made by a source at a point in time. Not ground truth — a claim. Facts are labeled, directed edges between entity nodes (or between an entity and a Day node).

### Fact edge schema

Every fact edge carries:

| Field | Present on | Meaning |
|---|---|---|
| `fact` | all | Plain language, close to source text. Never normalised or paraphrased. |
| `confidence` | all | `inferred` / `stated` / `verified` / `retracted` |
| `source_record` | all | Record ID that produced this fact |
| `source_at` | all | When the source record was created (event time) |
| `recorded_at` | all | When PearScarf indexed this fact (transaction time) |
| `stale` | all | True if a newer fact exists for this (entity, edge label, fact_type, to) |
| `replaced_by` | all | Edge ID of the fact that replaced this one. Null if current. |
| `valid_until` | optional | Date until which this fact is valid. Used for commitments, promises, goals. Indexed for deadline queries. |
| `fact_type` | all | Specific sub-type within the edge label. See full lists below. |

A fact is **current** when `stale=false` and `replaced_by=null`.

### Confidence values

The `confidence` field describes how well-supported a fact is and who established that level of trust:

| Value | Meaning | Set by |
|---|---|---|
| `inferred` | Concluded from context — email domain implies employment, first name implies person | Indexer on write |
| `stated` | Explicitly said in a record — someone wrote or said this directly | Indexer on write |
| `verified` | Confirmed by an authoritative external source (LinkedIn, official record, human HIL confirmation) | Verification agent or HIL |
| `retracted` | Recorded but subsequently found to be incorrect or explicitly withdrawn | Verification agent or HIL |

---

## Bi-temporal model

Every fact edge carries two timestamps tracking two independent timelines:

- **`source_at`** — when this happened in the real world. Derived from the record's own timestamp (email sent date, issue `created_at`, etc.)
- **`recorded_at`** — when PearScarf learned about it and wrote it to the graph.

**Why both matter:** Records can arrive out of order. A forwarded email processed today has `source_at` in January but `recorded_at` today. Without `source_at`, PearScarf would treat January information as newer than March information already in the graph — corrupting the factual timeline.

**`source_at` for specific record types:**
- Emails: sent timestamp
- Linear issues: `created_at`
- Linear change records: the change's own timestamp

---

## Edge labels

The graph db relationship type (edge label) is `AFFILIATED` / `ASSERTED` / `TRANSITIONED`. Every fact maps to exactly one. The `fact_type` property holds the specific sub-type within each label — pre-populated but extensible. `other` is always valid when the extractor cannot confidently assign a sub-type.

---

### AFFILIATED

Organizational attachment. Who belongs to what. Multiple simultaneous affiliations are valid — a person can be an employee at one company and an advisor at another at the same time.

The `role` property on the edge carries any further specificity (e.g. "senior engineer", "legal counsel"). Role is context only — not part of the dedup key.

**Write rule:** newer `source_at` for same (entity, `fact_type`, target) supersedes older.

| `fact_type` | Meaning |
|---|---|
| `employee` | Full-time employment |
| `contractor` | Hired for specific scope of work |
| `advisor` | Formal advisory relationship |
| `board_member` | Sits on the board |
| `founder` | Founded the company |
| `investor` | Has invested in the company |
| `legal_counsel` | Provides legal services |
| `consultant` | Provides consulting services |
| `owner` | Responsible and accountable for a project or initiative |
| `contributor` | Actively working on a project without owning it |
| `reviewer` | Reviewing or approving work on a project |
| `stakeholder` | Has meaningful interest in the outcome |
| `subsidiary` | Company is a subsidiary of another |
| `sub_project` | Project is a component of a larger project or deal |
| `other` | Clear affiliation, unclear type |

**Example:**
```
James Whitfield -[AFFILIATED, fact_type=employee, role="VP of Engineering"]-> Meridian Systems
```

---

### ASSERTED

Any claim, commitment, evaluation, decision, or judgment made by an entity about the world.

**Write rule:** accumulates. Multiple assertions of different `fact_type` or on different topics coexist. Same (entity, ASSERTED, `fact_type`, target) with newer `source_at` supersedes.

| `fact_type` | Meaning |
|---|---|
| `commitment` | Forward-looking obligation — "I will do X by Y" |
| `promise` | Softer than commitment — "we plan to", "we intend to" |
| `decision` | A choice was made or conclusion reached |
| `evaluation` | Actively assessing something — "we are evaluating X" |
| `opinion` | A stated view or judgment — "I think X" |
| `concern` | Something is being flagged as worrying |
| `blocker` | Something is impeding progress |
| `request` | Asking another entity to do something |
| `update` | Informational — "FYI, X happened" |
| `risk` | Something that might become a problem |
| `goal` | An aspiration or target |
| `reference` | One thing mentioned in the context of another |
| `other` | Clear assertion, unclear type |

**Example:**
```
Marcus Webb -[ASSERTED, fact_type=commitment, valid_until=2026-03-16]-> Meridian Deal
fact: "Marcus Webb committed to deliver the contract markup by end of day March 16"
```

---

### TRANSITIONED

An observed state change of an entity. Not a claim — an observed fact recorded by a system or explicitly stated as having occurred.

**Write rule:** always write new edge. Forms a chain. Nothing supersedes a transition — they are all real events.

| `fact_type` | Meaning |
|---|---|
| `status_change` | Project or issue moved between statuses |
| `stage_change` | Deal or project moved between lifecycle stages |
| `role_change` | A person's role or title changed |
| `ownership_change` | Ownership or responsibility transferred |
| `resolution` | Something previously blocked or open got resolved |
| `completion` | Something was finished |
| `cancellation` | Something was stopped or abandoned |
| `other` | Clear transition, unclear type |

**Example:**
```
Meridian API Integration -[TRANSITIONED, fact_type=status_change]-> Day[2026-03-13]
fact: "ENG-101 status changed from Blocked to In Progress"
```

---

## Day nodes

Not every fact has a meaningful `to` entity. When the `to` entity is absent or unresolvable, the fact is anchored to a **Day node** derived from `source_at` — the date the source record was created. Day nodes have one meaning: this fact entered the world on this day.

**Day node format:** local calendar date in the deployment timezone (default: `America/Los_Angeles`). Stored as `YYYY-MM-DD`. All timestamps stored UTC.

**`valid_until` is an edge property only** — not used for Day node anchoring. Day nodes always derive from `source_at`. The `valid_until` date is indexed separately for deadline queries.

**Examples:**
```
# Blocker with no to-entity -> anchored to the record date
Meridian API Integration -[ASSERTED, fact_type=blocker]-> Day[2026-03-12]
fact: "OAuth auth endpoint returning 403"

# Commitment with valid_until -> anchored to source_at (the email date), not the deadline
Marcus Webb -[ASSERTED, fact_type=commitment, valid_until=2026-03-16]-> Day[2026-03-14]
fact: "Marcus committed to deliver contract markup by March 16"
```

---

## Write loop

The indexer's write loop is structurally focused: it checks for **literal duplicates** before writing.

Before every `create_fact_edge` call, the indexer queries for an existing edge matching all of: `(from, to, edge_label, fact_type, source_record, fact)`. If found, the source record is appended to the edge's `source_records` list — no new edge is created. If not found, a new edge is created.

This check prevents duplicate edges from re-indexing the same record. It does not perform semantic deduplication, supersession, or staleness checks — those are the responsibility of the Curator.

## Staleness and supersession

The `stale` and `replaced_by` fields are set by the **verification & augmentation agent**, not the indexer.

Between writes and the Curator running, the graph may contain redundant or semantically equivalent facts. This is by design — the graph is eventually consistent. Structurally correct at write time, semantically correct after the Curator runs. See [Curator](curator.md) for details.

When the Curator runs:

- **AFFILIATED/ASSERTED**: newer `source_at` for same (entity, edge label, fact_type, target) supersedes older — sets `stale=true`, `replaced_by=<new edge id>`
- **TRANSITIONED**: never staled — every transition is a real event in the chain

No deletion. No overwriting. History is always preserved.

---

## Entity resolution

Entity resolution is handled inline by the extraction agent. The agent has read-only graph tools (`find_entity`, `search_entities`, `check_alias`, `get_entity_context`) and uses them during extraction to look up candidates before deciding whether a mention matches an existing entity or introduces a new one.

When the agent resolves a mention to an existing entity under a different surface form, it writes an IDENTIFIED_AS self-edge. One edge per unique surface form, deduplicated via MERGE. `source_records` accumulates all records that confirmed the alias.

Uncertainty surfacing (for cases the agent cannot confidently resolve) is future work — see PEA-11 / PEA-117.

---

## Canonical fact object

This is the shape returned by all MCP query tools:

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

`source_url` is null when the source record type has no linkable URL.

---

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `TIMEZONE` | `America/Los_Angeles` | Local timezone used for Day node date derivation |