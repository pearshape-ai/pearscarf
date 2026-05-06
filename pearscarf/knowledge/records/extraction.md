# Records expert — extraction guidance

You are processing a record submitted via the records expert (PearScarf's default MCP record-submission surface). These records are NOT records polled from external systems (Gmail, Linear, GitHub) — they are records authored directly by an operator or agent and submitted through the `submit_record` MCP tool.

## Record shape

```
Title: <single-line title>

Id: <unique record identifier>
Date: <YYYY-MM-DD>

<scope-conventional anchor line — e.g. "Shipped in pearscarf X.Y.Z." for a comms record>

## For humans

<brief prose narrative — context, why, alternatives>

## For agents

```yaml
facts:
  - "<plain-language sentence stating one fact>"
  - "<another fact>"
```
```

The full client-facing format spec lives at `pearscarf/knowledge/records/format.md`.

## How to extract

The `## For agents` `facts:` list is the **structured input**. Each entry is a plain-language sentence already stating one graph fact at graph-fact granularity. The author committed to those exact sentences as the truth. Your job is to label and store them — not to re-extract them from prose.

For each entry under `facts:`:

1. **Identify the subject entity.** It's the first concrete named entity in the sentence (the author followed subject-first prose discipline). Use entity-resolution tools (`find_entity`, `search_entities`, `check_alias`, `get_entity_context`) to find or create the entity.
2. **Pick the edge label.** Map the sentence's intent:
   - State changes / things that shipped, completed, transitioned → `TRANSITIONED`
   - Decisions, opinions, claims, commitments, goals → `ASSERTED`
   - Affiliations (X works at Y, X owns Y, X is a sub-project of Y) → `AFFILIATED`
3. **Pick the fact_type.** Use the deployment vocabulary for the chosen edge label (see `data-model.md` for canonical types: `decision`, `commitment`, `feature_shipped`, `status_change`, `employee`, etc.). When unsure between two close types, prefer the more specific one.
4. **Determine the target.**
   - If the sentence names another concrete entity that is the *object* of the fact (e.g. "Linda is the comms agent for **PearScarf**"), use it as the target.
   - Otherwise, the target is the Day node anchored to the record's `Date`.
5. **Set the fact_text.** Use the sentence as written. Don't paraphrase — the author committed to specific phrasing for a reason. Quote phrases, version numbers, and proper names exactly.
6. **Set provenance.**
   - `source_at` = record's `Date` (already on the record's metadata).
   - `source_record` = record id.
   - `source_url` = record's `source_url` metadata (from the submit URL).
   - `op_area` = record's `metadata.op_area` (set at submit; defaults to `reality`).

## What NOT to do

- **Don't re-extract from `## For humans`.** That section is the human-readable companion to the structured facts. Treating the prose as a second source of facts produces duplicates.
- **Don't fragment a single fact into multiple edges.** If a sentence says *"PearScarf 1.28.2 ships an `op_area` property — values 'reality' and 'intention', default 'reality', additive."*, that's ONE fact with rich context inline. Don't split into "ships op_area" + "values are reality and intention" + "default is reality" + "purely additive."
- **Don't merge unrelated facts.** Each entry under `facts:` is one fact. Don't combine adjacent entries.
- **Don't rewrite or paraphrase the sentence.** The fact_text is the author's wording.
- **Don't infer facts the author didn't list.** If the prose mentions something the agents-block doesn't, treat it as context, not a fact.

## Edge cases

- **Empty `facts:` list.** Skip the record. Don't fall back to LLM-extracting from prose. The author chose to record this without facts; respect that.
- **Sentence with no clear subject entity.** Rare — author discipline says start with a named entity. If you can't resolve a subject, log a warning and skip the fact.
- **Multiple named entities in one sentence.** The first is the subject. Subsequent named entities are content (mentioned in fact_text) — only the *direct object* of the relationship becomes the target; others are not extracted as additional edges from this fact.
- **Op_area on the record vs op_area on individual facts.** v1: every fact extracted from this record carries the record's `op_area`. Per-fact op_area overrides land later if/when the format spec adds them.
