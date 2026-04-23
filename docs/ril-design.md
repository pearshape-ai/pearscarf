# RIL Solution

Agreed pieces of the design. Populated gradually as we lock each section.

---

## Architecture — thin MCP layer over an internal core

The RIL system has two distinct layers:

- **Internal core** — producers, queue, handlers, pending-vector safety net. Pure pearscarf. No protocol dependency.
- **MCP protocol layer** — the wire between external resolvers and the server. Thin. Swappable.

### Components

```
┌──────────────────────────────────────────────────────────────┐
│                    External Resolvers                        │
│                                                              │
│  Claude Desktop    Discord bot    Agent script    CLI        │
│        │                │              │            │        │
│        └────────────────┴──────────────┴────────────┘        │
│                          │                                   │
│                    (MCP clients)                             │
└──────────────────────────┼───────────────────────────────────┘
                           │ JSON-RPC, bidirectional
                           │ (HTTP+SSE / stdio / Streamable HTTP)
┌──────────────────────────▼───────────────────────────────────┐
│                Pearscarf MCP Server                          │
│                                                              │
│   Tools (client → server):                                   │
│     hil_list   hil_get   hil_claim   hil_resolve   hil_release│
│                                                              │
│   Elicitation (server → client):                             │
│     elicitation/create — push an item to a connected client  │
└──────────────────────────┼───────────────────────────────────┘
                           │ (in-process function calls)
┌──────────────────────────▼───────────────────────────────────┐
│                     Internal Core                            │
│                                                              │
│   Producers → Queue → Handler → Graph writes                 │
│                                                              │
│   Producers: triage agent, extraction agent                  │
│              (future: curator, V&A)                          │
│                                                              │
│   Also: pending-vector safety net                            │
│         (record pushed on enqueue, popped on close)          │
└──────────────────────────────────────────────────────────────┘
```

### Flow — item lifecycle with elicitation

Push path (preferred when a resolver is connected):

```
Producer (internal code)              External Resolver (MCP client)
────────────────────                  ──────────────────────────────
enqueue_hil(...)
    │
    ▼
┌────────────────┐
│  Queue row     │
│  + push record │
│  to pending    │
│  vector coll.  │      elicitation/create       ┌────────────────┐
└───────┬────────┘ ────────────────────────────▶ │  Resolver UI   │
        │                                        │  (Claude chat, │
        │                                        │   Discord msg, │
        │                                        │   CLI prompt)  │
        │                                        └────────┬───────┘
        │                                                 │
        │                                        user/agent decides
        │                                                 │
        │       elicitation response                      ▼
        │ ◀──────────────────────────────────────────────┘
        ▼
Handler applies resolution:
   lineage sweep if needed,
   graph writes,
   queue row marked resolved,
   pop from pending vector.
```

Poll path (fallback when no resolver was connected at enqueue time, or for agents that prefer pull):

```
Resolver                        Server
────────                        ──────
hil_list()           ───▶       returns open items
hil_claim(id)        ───▶       atomic transition to 'claimed'
hil_resolve(id,...)  ───▶       handler applies resolution
```

Queue is the durable source of truth. Elicitation is the push optimization. Items live until resolved regardless of which path delivers the response.

---

## Where each channel fits

All four external surfaces speak the same MCP protocol:

- **Claude Desktop / Claude Code** — connected as an MCP client; pearscarf's elicitation surfaces in the chat for the operator. Human is the resolver.
- **Discord bot** — MCP client that translates elicitations into Discord messages and Discord replies back into elicitation responses. Human is the resolver, Discord is the UX.
- **Agent script** — custom MCP client that auto-resolves routine cases via its own LLM and falls back to polling + enqueueing tougher items. Agent is the resolver.
- **CLI (`psc hil ...`)** — MCP client for operator terminal use. Human is the resolver.

Same protocol, same tools, different UX. No per-surface code in pearscarf's core.

---

## Swap-ready

If MCP is replaced by something else (REST/WebSocket, A2A, whatever's next), only `pearscarf/mcp/mcp_server.py` (tool + elicitation bindings) needs to change. Internal core (`pearscarf/hil/` with producers, queue, handlers) stays invariant.

Dependency direction is one-way: protocol layer → service layer. Never the reverse.

---

## Case 1 — `er_ambiguity` end-to-end

### Trigger

The extraction agent flags an entity as uncertain when **all three** are true:

1. `search_entities` or `check_alias` returned 2+ candidates with exact name/alias match to the surface form.
2. The record carries no unique identifier (email, ID, URL, full title) that matches exactly one candidate.
3. After `get_entity_context` on each candidate, no candidate's facts differentially align with the record's content — both remain plausible.

Agent commits a **best guess** (its most plausible pick) and attaches an `uncertain` field on that entity in the `save_extraction` output.

### Agent output shape

```json
{
  "entities": [
    {
      "name": "Chen",
      "resolved_to": "node_sarah_chen",
      "uncertain": {
        "alternatives": ["node_david_chen"],
        "reasoning": "Two Chens at Acme, both active; record has no email/title to disambiguate."
      }
    },
    {"name": "Meridian", "resolved_to": "node_meridian"}
  ],
  "facts": [ ... ]
}
```

Confident entities omit `uncertain`. Uncertainty is per-entity, not per-record.

### Commit nothing (all-or-nothing per record)

On receiving the extraction output, if **any** entity has an `uncertain` field:

1. **Commit nothing to the graph.** The extraction output for this record is not written to Neo4j.
2. **Enqueue HIL items** — one `hil_queue` row per `uncertain` entity, each with `case_type='er_ambiguity'`.
3. **Push the record** into the pending vector collection (one push regardless of how many HIL items the record spawned).
4. **Pipeline moves on** — next record extracts normally. This record is deferred until resolution arrives.

If no entity is uncertain, the extractor commits normally as today. Commit-nothing only kicks in when uncertainty exists.

**Why commit-nothing:** aligned with the *"missing is OK, wrong is poison"* principle. Tentative facts aren't allowed to pollute the graph. Pending-vector safety net keeps the record visible to agents during the window; structured facts arrive after resolution.

### Elicitation request (server → resolver)

**One elicitation per record** — all uncertainties bundled into a single request. Resolver sees the full record context once, resolves everything together.

Pre-rendered prose message + structured schema keyed by queue row id:

```json
{
  "method": "elicitation/create",
  "params": {
    "message": "Record has 2 resolutions needing review.\n\nRecord: email from pm@acme.com, 2026-04-15, subject \"Re: launch plan\".\nExcerpt: \"...Chen had concerns about the timeline for Meridian...\"\n\n--- Resolution 1 (queue_row_abc123) ---\nSurface form: \"Chen\"\nCandidates:\n  1. Sarah Chen (node_sarah_chen) — Senior Engineer at Acme, active on prior launches\n  2. David Chen (node_david_chen) — PM at Acme, flagged timeline concerns on ACM-92 last week\nReason for flag: Two Chens at Acme, both active; record has no email/title to disambiguate.\n\n--- Resolution 2 (queue_row_def456) ---\nSurface form: \"Meridian\"\nCandidates:\n  1. Meridian Systems (node_meridian_co) — Company\n  2. Meridian API Integration (node_meridian_proj) — Project\nReason for flag: Partial name overlap across entity types; record doesn't differentiate.",
    "requestedSchema": {
      "type": "object",
      "properties": {
        "queue_row_abc123": {
          "type": "object",
          "properties": {
            "chosen_id": { "enum": ["node_sarah_chen", "node_david_chen", null] },
            "reasoning": { "type": "string" }
          },
          "required": ["chosen_id", "reasoning"]
        },
        "queue_row_def456": {
          "type": "object",
          "properties": {
            "chosen_id": { "enum": ["node_meridian_co", "node_meridian_proj", null] },
            "reasoning": { "type": "string" }
          },
          "required": ["chosen_id", "reasoning"]
        }
      },
      "required": ["queue_row_abc123", "queue_row_def456"]
    }
  }
}
```

For single-uncertainty records, the bundle has one sub-object. Same mechanism.

### Resolver response shape

MCP's three possible actions:

- `accept` with content matching the schema — handler proceeds.
- `reject` — resolver declines; items stay open, can be re-elicited or polled by another resolver.
- `cancel` — user closed the dialog; same effect as reject.

Accept payload (all resolutions at once):

```json
{
  "action": "accept",
  "content": {
    "queue_row_abc123": {
      "chosen_id": "node_david_chen",
      "reasoning": "David's timeline concerns on ACM-92 match the email content."
    },
    "queue_row_def456": {
      "chosen_id": "node_meridian_proj",
      "reasoning": "'Meridian' in context of launch timeline refers to the project."
    }
  }
}
```

### Handler — what happens on accept

**Re-extraction with resolutions as hints.** Nothing is in the graph yet (commit-nothing strategy), so there's no lineage sweep to do. We just run extraction again, this time with the resolved surface forms as authoritative inputs.

Steps:

1. **Mark all queue rows for this record `resolved`.** Store each `resolution` JSON on its row.
2. **Re-run the extraction agent on the record**, passing a new optional input `pre_resolved`:
   ```json
   { "Chen": "node_david_chen", "Meridian": "node_meridian_proj" }
   ```
   (null values become "create new entity with this surface form as canonical".)
3. The agent treats `pre_resolved` mappings as authoritative during ER — no looking up candidates for those surface forms.
4. Agent outputs a clean `save_extraction` with no `uncertain` fields (if the resolutions cover every uncertainty, which they do since we bundled).
5. **Commit the full output to Neo4j.** Entities + facts all land.
6. **Pop the record from the pending vector collection.**

### Close-out

- All queue rows for this record are `resolved` before re-extraction starts. Handler waits until the full bundled response is in before triggering re-extraction.
- After successful commit, the record's lifecycle in HIL is over.

### Full sequence diagram

```
Extractor                 Queue/Storage              Resolver (MCP client)
─────────                 ─────────────              ─────────────────────
save_extraction(
  entities incl. uncertain,
  facts
)
   │
   │  (any uncertain?)
   │
   ├─── yes ───▶ do NOT commit to graph
   │
   ├──▶ enqueue_hil(er_ambiguity, ...) × N  (one row per uncertain entity)
   │
   └──▶ pending_vector.push(record)

                           elicitation/create (bundled: all uncertainties for this record)
                                     ──────────────────────────▶
                                                                  resolver reasons
                                                                  across all candidates
                                                                  decides all at once
                                           elicitation response (all resolutions)
                                     ◀──────────────────────────
   ┌─────────────────┐
   │  Handler        │
   │ (er_ambiguity)  │ mark all queue rows resolved
   │                 │
   │                 │ re-run extraction with pre_resolved hints:
   │                 │   { "Chen": "node_david_chen", ... }
   │                 │
   │                 │ extraction commits cleanly to Neo4j
   └─────────────────┘
   │
   └──▶ pending_vector.pop(record)
```

### Fallback — SLA expiry

Item(s) unresolved past `sla_at`:
- Log expiry.
- **Safe default for er_ambiguity: fall back to the agent's best guess.** Re-run extraction with `pre_resolved = { surface_form: best_guess_id }` for each expired item. Commit with a flag in the `resolution` row noting `resolver: "sla_default"`.
- Rationale: best_guess was plausible at the time; going with it is safer than leaving the record forever missing.
- Operator can still manually re-open via queue tools if they want to revisit.

### What this covers / what it doesn't

**Covers:**
- Detection (agent self-report via `uncertain` field per entity)
- Commit-nothing strategy — no graph writes until all uncertainties resolve
- Bundled elicitation (one request per record; all resolutions together)
- Re-extraction with `pre_resolved` hints after resolution
- Safety net via pending vector during the window
- Graceful expiry with best-guess fallback

**Doesn't cover (v1 deliberately):**
- Fact contradiction (`case_type='fact_contradiction'`) — same framework, different payload and handler; scaffolded in schema, not implemented.
- Curator-side uncertainty, V&A uncertainty — same framework, future producers.
- Auto-resolver for routine cases (cheap LLM polling queue and resolving) — enabled by the interface, to be added post-v1.
- Two-resolver consensus for high-stakes decisions — deferred.
- Per-uncertainty resolution within a record (partial acceptance) — bundle is all-or-nothing in v1.

---

## Case — `triage_uncertain` end-to-end

Simpler than `er_ambiguity`. Same framework, different handler.

### Trigger

The triage agent outputs `uncertain` instead of `relevant` or `noise`. This happens when onboarding + expert relevancy guidance + graph context don't resolve the question cleanly.

### Enqueue

1. Triage sets `classification='uncertain'` on the record.
2. Enqueue one `hil_queue` row with `case_type='triage_uncertain'`.
3. Record is already in the pending vector collection (it was there as `pending_triage`; staying as `uncertain` keeps it there).

Nothing else is written. Graph is untouched (extraction hasn't run yet).

### Elicitation request (bundled per record, same pattern)

```json
{
  "method": "elicitation/create",
  "params": {
    "message": "Record relevance needs review.\n\nRecord: email from unknown@somedomain.com, 2026-04-17, subject \"Quick question\".\nExcerpt: \"...wondering if you'd be open to a chat about...\"\n\nTriage's reasoning for flag: Unknown sender, cold outreach tone, but personally written and mentions a topic that might matter. Neither clearly marketing nor clearly operational.",
    "requestedSchema": {
      "type": "object",
      "properties": {
        "queue_row_xyz789": {
          "type": "object",
          "properties": {
            "classification": { "enum": ["relevant", "noise"] },
            "reasoning": { "type": "string" }
          },
          "required": ["classification", "reasoning"]
        }
      },
      "required": ["queue_row_xyz789"]
    }
  }
}
```

A record rarely has multiple triage_uncertain items (triage is one decision per record), so the bundle is typically a single entry. Same mechanism scales if it ever isn't.

### Handler on accept

1. **Mark queue row `resolved`.** Store resolution JSON.
2. **Flip classification on the record:**
   - `relevant` → Extraction picks it up on next poll; extraction runs normally (may produce new HIL items via er_ambiguity at that point — separate elicitation later).
   - `noise` → terminal state; record stays in the SOR but is never extracted.
3. **Pop from pending vector collection.**

No lineage sweep (nothing in the graph yet). No re-extraction (Extraction handles extraction normally when classification flips to relevant).

### Fallback — SLA expiry

Item unresolved past `sla_at`:
- **Safe default: fall back to `noise`.** Missing is safer than polluting the graph with an unreviewed record.
- Queue row state = `expired`. Classification set to `noise`. Pop from pending vector.
- Operator can reopen via queue tools.

### Interaction with `er_ambiguity`

Sequential, not parallel. A record's lifecycle through HIL can involve both case types, but only one at a time:

```
record arrives
   │
   ▼
triage agent
   │
   ├─ relevant  ─┬─▶ extraction
   │             │
   ├─ noise     ─┤   (extraction runs; may flag er_ambiguity)
   │             │
   └─ uncertain  ▼
       │         (if flagged, new HIL items for er_ambiguity;
       │          separate bundled elicitation)
       ▼
   triage_uncertain HIL item
       │
       ├─ resolved → relevant ─▶ (continues to extraction, above)
       └─ resolved → noise    ─▶ terminal
```

HIL items from later stages never share an elicitation with earlier-stage items — they arrive later in time. Bundling is per-record-per-stage, not cross-stage.

### What this covers / what it doesn't

**Covers:**
- Triage agent's `uncertain` verdict becomes an actionable queue item
- Simple binary resolution (relevant / noise)
- Handler just flips classification; natural Extraction pickup if relevant
- Safe default to `noise` on SLA expiry — conservative, preserves graph integrity

**Doesn't cover (v1 deliberately):**
- Overturning a previously-accepted classification (e.g., flipping a `relevant` record back to `noise` later) — that's the lineage-sweep case from the broader RIL discussion; not part of v1 triage_uncertain handling.
- Multi-classification verdicts (e.g., "relevant, but low priority") — the enum stays binary.

---

## Open questions — drill down before implementation

### Storage / data shape

- **Queue row schema** — lock the exact column list and types. Draft has a proposal; not yet in this doc.
- **`enqueue_hil` signature** and other storage helpers — not specified.
- **Resolution payload structure** stored on `hil_queue.resolution` — implied, not pinned.

### Pending vector collection

- **Detailed lifecycle** — push on enqueue, pop when no open items remain AND record is indexed-or-noise. Only mentioned in passing in this doc.
- **Vector + substring match mechanism** — deliberately dumb, no NER. Not captured.
- **Response shape** — pending records attach as a `pending_context` section on query responses. Not specified.
- **Hit cap** to prevent noise flooding — open question, not decided.
- **Read-only constraint for agents** (no facts derived from pending content) — discussed, not noted.

### Re-extraction wiring

- **Trigger mechanism** — synchronous on `hil_resolve`? Background daemon polling for all-resolved records? Callback from handler? Not specified.
- **`pre_resolved` contract** — is it a new parameter on the extraction agent? On `save_extraction`? Passed via the prompt? Not pinned.
- **`null` resolution path** (create new entity) — handler step exists for er_ambiguity but not detailed for the re-extraction flow.

### Concurrency / edge cases

- **Claim timeout** — what happens if a resolver claims and never resolves? Follow curator's timeout-reset pattern.
- **Race between resolvers** seeing the same elicitation — first-to-respond wins? Others receive a "no longer needed" signal?
- **No-resolver-connected case** — explicit fallback to polling, with what cadence?
- **Reject / cancel handling** — what concretely? Item stays open; re-elicit later; after how long?
- **Idempotency on re-extraction** — what if the agent flags the same uncertainty again on re-run? Loop guard.

### MCP surface

- **Concrete tool signatures** — `hil_list`, `hil_get`, `hil_claim`, `hil_resolve`, `hil_release` named but not specified.
- **Notifications vs elicitation** — do we use `notifications/*` for "new item arrived" pushes, or is elicitation the only server-initiated mechanism?

### Observability

- **Event logging** — where HIL events (enqueue, claim, resolve, expire) log to. LangSmith? pearscarf log?
- **Metrics** — queue depth, age of oldest item, resolution rate, time-to-resolve. Nowhere in this doc yet.

### Cross-stage interactions

- **Extraction behaviour on triage_uncertain → relevant** — implied (Extraction just picks up new `relevant` records). State explicitly.
- **Lineage sweep on later reclassification** — the case where a previously `relevant` record is later overturned to `noise` (e.g., by curator). Broader RIL concern; named as out-of-scope-for-v1 here but not treated.

### Maybe-overkill — worth flagging anyway

- **Eval / test approach** for HIL quality.
- **Tracing per-item lifecycle** (LangSmith spans end-to-end).
- **Claim-timeout reset on startup** (crash recovery, mirrors curator's pattern).
