## Linear extraction guidance

Linear records are issues filed in Linear. The body of a well-formed Done issue carries a `## For agents` YAML block declaring exactly which facts join the graph; when present, that block is the extraction source of truth. When absent, the body is treated as narrative and extracted as prose with the linearscarf-specific exclusions below.

The complete format spec lives in `knowledge/issue_format.md`.

### Path 1: `## For agents` YAML block (preferred)

When the issue body contains a `## For agents` section with a YAML block of the form:

```yaml
facts:
  - subject: <entity name>
    edge_label: TRANSITIONED | ASSERTED | AFFILIATED
    fact_type: <lower_snake_case>
    target: <entity name | (Day)>
    fact_text: <readable English sentence>
```

Extract by parsing the YAML and emitting one fact per entry:

- Resolve `subject` via standard entity resolution. Create a new entity only when no match is found.
- Resolve `target` the same way. The special target `(Day)` resolves to the day node for the issue's recorded date.
- Emit one fact via the save-extraction tool with:
  - `from_entity` = resolved `subject`
  - `to_entity` = resolved `target` (or the day node id for `(Day)`)
  - `edge_label`, `fact_type`, `fact_text` = verbatim from YAML
  - `confidence` = `stated` (the operator declared this fact in the issue)

Do not extract anything from the `## For humans` section or other prose when the YAML block is present — the YAML is the complete, intentional fact set.

### Path 2: prose fallback (no `## For agents` block)

When the issue body has no `## For agents` block, treat the body as narrative and extract facts using general extraction guidance, with these linearscarf-specific rules:

- **The issue itself is not an entity.** Do not create a graph node for the issue identifier (e.g. `ABC-142`).
- **Issue metadata is not extracted as facts.** Assignee, project, labels, status are structural — don't produce facts that just restate them (e.g. "Person X is assigned to Project Y" when both are already known from the issue's metadata fields).
- **The metadata `Project: <name>` line is the only project source.** Don't create other Project nodes from body text.
- **Illustrative examples are not facts.** Phrases like `Example:`, `e.g.`, `For example`, `Imagine`, `Hypothetical:`, quoted scenarios, sample input/output blocks — teaching material, not facts.

### Source timing

The fact's `source_at` is the issue's `linear_created_at` — never the indexing time.

### Issue change records (source_type: linear_issue_change)

Issue change records are field-level diff events on a parent issue and do not carry the `## For agents` block. When the record is an issue change (indicated by "Change:" in the content):

- One change = at most one TRANSITIONED fact (e.g. status change → TRANSITIONED/status_change).
- Reference the person who made the change if named in "Changed by: …".
- Reuse entities already named on the parent issue. Don't create new ones.
- Keep it minimal — at most one or two facts per change.
