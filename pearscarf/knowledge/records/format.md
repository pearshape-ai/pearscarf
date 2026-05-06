# PearScarf record format

**Format version:** 0.1.0

This spec describes the body shape of a record submitted to PearScarf via the MCP `submit_record` tool. Authors (humans or agents) write records following this shape; PearScarf parses each record, labels its facts, entity-resolves the subjects, and writes them to the graph. Authors capture *what reality is*; PearScarf decides *how the graph represents it*.

## Body shape

Every record's content is markdown with this exact top-to-bottom structure (the file or surface holding the content — `.md` file, Linear issue body, blog post, notion page — is the author's choice):

```
Title: <single-line title — what this record captures>

Id: <unique record identifier — stable across moves; e.g. 20260501-tagline-decision>
Date: <YYYY-MM-DD; the source-event date>

<Anchor line — convention varies by scope; comms records use "Shipped in pearscarf X.Y.Z."; design records use a doc-reference like "Designed in lab/design/...".>

## For humans

<Brief prose narrative, 1–3 paragraphs. What changed/decided, why. Don't pad — the agent block carries the structured signal; this section is the human-readable companion.>

## For agents

<a YAML list under the key `facts:` — see below.>
```

### Field descriptions

- **`Title`** — single-line, plain text. The record's headline.
- **`Id`** — unique, stable identifier. Same `Id` submitted again is the same record (PearScarf dedups on this). Format is your choice; date-prefixed slugs work well (e.g. `20260501-tagline-decision`).
- **`Date`** — `YYYY-MM-DD`. The source-event date. Becomes `source_at` on every fact extracted from this record.
- **Anchor line** — a short scope-specific anchor immediately under `Date`. Comms records typically use *"Shipped in pearscarf X.Y.Z."*; design records use *"Designed in <path>."*. Conventions are by scope, not by format.
- **`## For humans`** — brief narrative. Discipline below.
- **`## For agents`** — a YAML list under the key `facts:`. Each entry is a plain-language sentence stating one graph fact. Discipline below.

## `## For humans` — the narrative

Brief prose narrative. The companion to the structured facts in `## For agents`. Both humans and agents read this — agents may quote or summarise from it — so keep it dense and specific.

### Author discipline

- **1–3 paragraphs.** Tighter is better. If you're writing four, you're padding.
- **Lead with the change, not the framing.** First sentence states what changed. Second paragraph (if any) gives the why or the prior context.
- **Specific names, versions, phrases, dates inline.** Quote the exact phrase that was locked, the version that shipped, the alternatives that were rejected.
- **No filler or marketing language.** Skip "we are pleased to announce", "this exciting new feature", "as you know". Skip the AI-hype vocabulary (`revolutionary`, `intelligent`, `next-generation`, `game-changing`).
- **Self-contained.** Don't reference external context the reader doesn't have. If a term needs a definition, define it inline.
- **No new headings.** The two `## For humans` / `## For agents` headings are the only structural markdown the format prescribes.

## `## For agents` — the facts list

Each entry is one plain-language sentence. PearScarf reads the list and, for each entry, picks the appropriate graph edge label, the appropriate fact_type, and the subject + target entities to write to the graph.

```yaml
facts:
  - "<one rich, contextual sentence stating one fact>"
  - "<another fact, same shape>"
```

### Author discipline

- **One fact = one graph fact.** Each sentence states *one* event, decision, observation, or affiliation. Don't fragment a single concept across multiple sentences; don't merge two unrelated assertions into one sentence.
- **Subject-first prose.** Start each fact with the subject entity by name (`PearScarf`, `Linda`, `Acme Corp`). The first concrete entity in the sentence is the most reliably resolved by PearScarf's entity resolver.
- **Plain language; no graph terminology.** Never use words like `edge_label`, `fact_type`, `TRANSITIONED`, `ASSERTED`, `target`, etc. PearScarf decides those. Author writes natural sentences.
- **Pack contextual nuance into the sentence.** A claim like *"PearScarf 1.28.2 ships an `op_area` property — values 'reality' and 'intention', default 'reality', additive."* is one rich fact. Don't decompose into five sentence-fragments.
- **Typically 1–2 facts per record.** If you find yourself writing 5+, the granularity is too fine — fold related fragments back into single contextual sentences.

## Submit-time fields

Submit alongside the body via the MCP `submit_record` tool:

- **`url`** — required, non-empty. A URL pointing to where the record is persisted (your `sor` repo, a blog post URL, etc.). Becomes `source_url` on every fact extracted from this record. PearScarf does **not** fetch the URL; non-emptiness is the only check.
- **`op_area`** — `"reality"` (default) or `"intention"`. Marks whether the record describes something that has shipped / been observed (`reality`) or is planned / committed (`intention`). PearScarf threads this onto every fact extracted from the record.

*Note: when the scopes mechanism lands, `op_area` will become one dimension within multi-valued scopes (e.g. `["comms", "internal", "reality"]`). The format spec evolves at that point; for now, `op_area` is the only categorisation axis.*

## What PearScarf does on receipt

1. Parses the record's body — title, id, date, anchor, sections.
2. Validates required fields are present.
3. For each entry under `facts:`, picks an edge label and fact_type, finds-or-creates the subject entity, and writes the fact edge to the graph.
4. Sets `source_at` from `Date`, `recorded_at` to now, `source_record` to the record id, and `source_url` from the submit's `url`.
5. Returns `{record_id, status: "queued"}` to the client. Use `get_record_status(record_id)` to check when extraction completes.

## Examples

### Comms decision

````
Title: Lock PearScarf tagline as "Shared operational brain for teams of AI coworkers"

Id: 20260501-tagline-decision
Date: 2026-05-01

Shipped in pearscarf 1.28.11.

## For humans

PearScarf's public tagline is now "Shared operational brain for teams of AI coworkers." The README front-matter was repositioned around this framing in 1.28.11, replacing the prior "self-improving context engine for teams of agents" line.

The decision is a category-creation bet: the public lede frames PearScarf as the substrate for AI coworkers (the rising 2026 metaphor for collaborative agents) rather than competing inside the existing memory/context category.

## For agents

```yaml
facts:
  - "PearScarf locked its public tagline as 'Shared operational brain for teams of AI coworkers' in 1.28.11, replacing the prior 'self-improving context engine for teams of agents' framing in the README front-matter."
  - "PearScarf chose 'AI coworkers' over 'worker agents' for the headline noun after term-availability research surfaced muddied connotations of 'worker agents' across Sema4.ai and orchestrator-pattern literature."
```
````

Submit-time: `url: "https://github.com/.../20260501-tagline-decision.md"`, `op_area: "reality"`.

### Product change

````
Title: Add op_area property to fact edges

Id: 20260429-op-area-property
Date: 2026-04-29

Shipped in pearscarf 1.28.2.

## For humans

Until 1.28.2 every fact in the graph was implicitly "things observed" — there was no structural way to distinguish facts about reality (what shipped, deployed, observed) from facts about intention (what's planned, committed). With multiple agent sessions writing to the same graph, conflating the two caused drift.

PearScarf 1.28.2 adds an `op_area` property on every fact edge written by `graph.create_fact_edge`. Default is `"reality"`; `"intention"` is the explicit opt-in. The change is purely additive — existing callers inherit the default.

## For agents

```yaml
facts:
  - "PearScarf 1.28.2 ships an `op_area` property on every fact edge written by `graph.create_fact_edge` — values 'reality' (observed/shipped/deployed) and 'intention' (planned/committed/drafted), default 'reality', purely additive."
  - "PearScarf chose `op_area` as the dedicated separator for reality vs intention to keep multi-agent graph writes from drifting; without it, a planned launch read as already-shipped and a postponed objective looked completed."
```
````

Submit-time: `url: "https://github.com/.../20260429-op-area-property.md"`, `op_area: "reality"`.
