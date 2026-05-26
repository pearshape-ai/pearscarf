# PearScarf record format

**Format version:** 0.1.1

This spec describes the body shape of a record submitted to PearScarf via the MCP `submit_record` tool. Authors (humans or agents) write records following this shape; PearScarf parses each record, labels its facts, entity-resolves the subjects, and writes them to the graph. Authors capture *what reality is*; PearScarf decides *how the graph represents it*.

## What a record is for

PearScarf's graph is **shared operational reality** — every agent across the operation reads it, not just the producer or the producer's peers. A record is the surface where each operator's domain-bound work becomes shared truth. The author lives in their domain (code, design, customer interactions, deploy infrastructure, brand voice, contracts) and naturally first-drafts from there; the discipline is to lift one level above the domain before each fact lands in `## For agents`.

**Three non-negotiable rules** apply to every fact in every record. They are not optional and not opinion — every author writing to this graph (human or agent) follows them on every fact, every time:

1. **One dimension per record.** A record touches a single domain. When two domains are involved — even causally linked ones (e.g. a product change *and* the deploy of that change) — write two records, one per domain.

2. **Work-only facts.** Every fact must be true *as a result of the work this record captures.* Standing policies, default profiles, background state, or generally-true claims belong in separate ingest records. Test: would the fact have been true an hour before the record's `Date`? If yes, it does not belong here.

3. **State what is now true; not how it was made true.** The work is the producer's domain artifact — a code path, a deployed config, a contract clause, a brand-voice decision. The fact is the *operational delta* in shared reality — what is now possible, what someone in another role can rely on, what is removed as a manual step. The implementation is not the change; it is the proof of the change in the producer's medium. Test: could an agent outside the producing domain act on this fact? If only the author's peers can, the framing is too internal — strip the file paths, code identifiers, prompt-section names, ticket IDs, internal jargon, and ask whether a substantive operational claim remains.

   **Include the consumer-facing handle the consumer uses to act on the delta** — a CLI flag (`--debug`), an MCP tool (`submit_record`), a resource URI (`pearscarf://format/record`), an env var (`DEPLOYMENT_VOCAB_PATH`), a config-file shape (`vocab.yaml`), a contract section reference. The handle is *part of* the delta, not the mechanism behind it. Strip-test each specific term in the fact: would the consumer ever type, call, fetch, or reference this thing? Keep what passes; strip what doesn't.

A fact that violates any of these three rules is not ready for the graph. Fix the fact before submitting — the curator deduplicates, but does not catch framing problems. **There is no exception for "small" records, "obvious" facts, or "I'll fix it later" — the discipline applies on every fact, every time.**

Two takes on the same engineering change:

❌ Domain-private:
> *PearScarf 1.29.9 surfaces `deployment_vocab` entity types in the regular extraction prompt; the vocab was previously only injected for seed-mode prompts.*

✅ Shared reality:
> *PearScarf 1.29.9 lets operators add their own entity types to extraction by declaring them in a `vocab.yaml` file (pointed to by the `DEPLOYMENT_VOCAB_PATH` env var) — records mentioning operator-declared types are now resolved by name across all extraction, not just on seeds.*

The second is the operational delta — readable by any agent in the graph, actionable for release copy, decision-support, downstream tooling. The first describes how the producer made the delta happen, useful only to other engineers.

**Pick framing for the edge shape you want.** The same change can be written two ways and land as different graph edges:

- *State-change* framing (`X became Y`, `X is now Y`, `X transitioned to Y`) biases the extractor toward `TRANSITIONED` with the changed entity as the subject and the affected party as the target.
- *Decision/usage* framing (`Actor decided X`, `Actor uses Y`, `Actor adopted Y`) biases toward `ASSERTED` with the actor as the subject and the object of the action as the target.

Both can land as two-entity edges. Pick the framing whose subject-target direction is the one you'd want to read on the resulting fact — the LLM follows the framing more reliably than it second-guesses it.

## Body shape

Every record's content is markdown with this exact top-to-bottom structure (the file or surface holding the content — `.md` file, Linear issue body, blog post, notion page — is the author's choice):

```
Title: <single-line title — what this record captures>

Id: <unique record identifier — stable across moves; e.g. 20260501-tagline-decision>
Date: <ISO 8601 datetime with timezone, e.g. 2026-05-12T14:33:51Z>

<Anchor line — convention varies by scope; comms records use "Shipped in pearscarf X.Y.Z."; design records use a doc-reference like "Designed in lab/design/...".>

## For humans

<Brief prose narrative, 1–3 paragraphs. What changed/decided, why. Don't pad — the agent block carries the structured signal; this section is the human-readable companion.>

## For agents

<a YAML list under the key `facts:` — see below.>
```

### Field descriptions

- **`Title`** — single-line, plain text. The record's headline.
- **`Id`** — unique, stable identifier. Same `Id` submitted again is the same record (PearScarf dedups on this). Format is your choice; date-prefixed slugs work well (e.g. `20260501-tagline-decision`).
- **`Date`** — ISO 8601 datetime with explicit timezone (`2026-05-12T14:33:51Z` or `2026-05-12T07:33:51-07:00`). The source-event time. Becomes `source_at` on every fact extracted from this record — curation orders facts by this value, so include the time, not just the day, to disambiguate same-day records. Date-only `YYYY-MM-DD` is still accepted and is treated as `T00:00:00Z`, but the typed value gives the curator finer ordering. Naive datetimes (no `Z` or offset) are rejected at submit time.
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
- **Distinct facts within a record.** Two facts in the same record must not share both subject and underlying claim. If they do — e.g. *"X decided to create the AI coworkers category"* and *"X chose 'AI coworkers' as the headline term"* — they are either one fact (merge — pack the nuance into a single contextual sentence) or you need to make their claims structurally distinct (different subjects, different aspects, different anchored targets). The curator treats a record's facts as an atomic coherent set and won't adjudicate between them; downstream readers will struggle with overlapping claims regardless.
- **Subject-first prose.** Start each fact with the subject entity by name (`PearScarf`, `Linda`, `Acme Corp`). The first concrete entity in the sentence is the most reliably resolved by PearScarf's entity resolver.
- **Use the graph's canonical names — resolve before you submit.** Before finalizing a fact, look up its subject (and any key target) in the live graph (`get_entity_context` or `recall`) and use the *exact* name the graph already knows the entity by — the `resolved_to` value it returns. If the lookup comes back `not_found`, or returns `alternatives` (ambiguous), you are creating or forking an entity — make that an intentional choice, not an accident of phrasing. Writing "the dogfood deployment" when the graph knows it as `psc-dogfood-vm` either spawns a duplicate node or silently fails to merge into the real one.
- **Plain language; no graph terminology.** Never use words like `edge_label`, `fact_type`, `TRANSITIONED`, `ASSERTED`, `target`, etc. PearScarf decides those. Author writes natural sentences.
- **Pack contextual nuance into the sentence.** A claim that bundles what shipped, the values it accepts, the default, and that it's purely additive into one rich sentence is one fact. Don't decompose into five sentence-fragments.
- **Typically 1–2 facts per record.** If you find yourself writing 5+, the granularity is too fine — fold related fragments back into single contextual sentences.

## Submit-time fields

Submit alongside the body via the MCP `submit_record` tool:

- **`url`** — required, non-empty. A URL that resolves back to where the record is persisted in your shared store (a github file, a wiki page, a blog post — any resolvable URL). Becomes `source_url` on every fact extracted from this record. PearScarf does **not** fetch the URL; non-emptiness is the only check.
- **`op_area`** — record-level routing. `"reality"` (default) sends the record through triage + extraction so its facts land in the graph. `"intent"` persists the record but skips the graph — intents are operational plans, not observed reality. A dedicated submission surface for intents is coming separately; for now, `op_area="intent"` records are accepted but do not yet have a consumer beyond persistence.

## Submission discipline

Records exist in two places: as a persistent artifact in your operation's **shared system of record**, and as facts in the PearScarf graph. Submission is the bridge between them, and the moves around submission matter as much as the body content.

A *shared system of record* is the durable store all your authors (humans and agents) read from and write to. PearScarf does not prescribe what it is — a git repo, a wiki, a document store, an artifact bucket — only that it exists, that the whole fleet can access it, and that every `url` submitted to PearScarf resolves there. The discipline below applies regardless of which store you've chosen; how you implement each step is your operation's choice.

**Three non-negotiable rules apply on every submission, every time:**

1. **Sync from the shared store before drafting.** Refresh your local view (`git pull`, re-read, re-list, whatever your store demands) before authoring a new record. Other authors may have published in parallel; starting from a stale view leaves your record orphaned, in conflict with concurrent work, or unaware of context you needed.

2. **Persist the record to the shared store *immediately* after writing it.** The moment the record content is final, push it to the store — commit, save, upload, whatever the store requires. Don't move on to other work; don't batch with adjacent edits; don't leave for "end-of-session." Records that exist only in a single contributor's local state are invisible to the fleet, prone to loss, and create coordination drag when other authors publish in parallel.

3. **Submit to PearScarf only after persistence is complete.** The `submit_record` MCP call carries the record's `url` — the resolvable path that points back to where the record lives in your shared store. The URL must resolve before submission so the fact's provenance link is valid the moment it lands in the graph.

No exceptions for "small" records, "draft" records, or "I'll commit it at end-of-session." Every record, every author, every time. The crew or operator manual is the right place to capture *which* shared store your fleet uses and how it's organized; this spec captures only the discipline that applies regardless.

## What PearScarf does on receipt

1. Parses the record's body — title, id, date, anchor, sections.
2. Validates required fields are present.
3. For each entry under `facts:`, picks an edge label and fact_type, finds-or-creates the subject entity, and writes the fact edge to the graph.
4. Sets `source_at` from the body's `Date:` value (parsed at ingest into `metadata.source_at`), `recorded_at` to now, `source_record` to the record id, and `source_url` from the submit's `url`.
5. Returns `{record_id, status: "queued"}` to the client. Use `get_record_status(record_id)` to check when extraction completes.

## Examples

### Comms decision

````
Title: Lock PearScarf tagline as "Shared operational brain for teams of AI coworkers"

Id: 20260501-tagline-decision
Date: 2026-05-01T15:30:00Z

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
Title: Curator now does LLM-judged supersession

Id: 20260510-curator-llm-judge
Date: 2026-05-10T18:42:00Z

Shipped in pearscarf 1.32.0.

## For humans

Until 1.32.0 the curator only marked exact-duplicate edges stale; sibling facts about the same underlying claim sat side-by-side in the graph. With multiple agent sessions writing similar facts in different phrasings, drift accumulated and downstream queries returned overlapping noise.

PearScarf 1.32.0 adds an LLM judge inside the curator. After extraction enqueues a record, the curator scans each new edge, finds non-stale siblings from the same subject (regardless of edge_label or fact_type), and asks the judge to label each pair as `trigger_supersedes_sibling`, `sibling_supersedes_trigger`, or `coexist`. Superseded edges are marked `stale=true` with `replaced_by` pointing to the survivor. A record's own edges are excluded from each other's sibling pools — they coexist by construction.

## For agents

```yaml
facts:
  - "PearScarf 1.32.0 ships LLM-judged supersession in the curator — each new edge is paired against same-subject sibling edges across all edge_labels and fact_types; the judge labels each pair as trigger_supersedes_sibling, sibling_supersedes_trigger, or coexist; the loser is marked stale=true with replaced_by pointing to the survivor."
```
````

Submit-time: `url: "https://github.com/.../20260510-curator-llm-judge.md"`, `op_area: "reality"`.
