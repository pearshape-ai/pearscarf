## Linear extraction guidance

Linear records are issue reports. **The issue itself is not an entity.** It is a source
document — extract facts and references FROM it, but don't create a graph node FOR it.

### The Project rule is absolute

For any Linear issue record, you may create AT MOST ONE `Project` entity from it, and it
is the exact value on the `Project:` metadata line near the top of the record content.
If the metadata line says `Project: Foo`, resolve that to the `Foo` Project (creating it
if new) — that is the project for this record.

**No other Project nodes are permitted, regardless of how they appear in the body.** The
following are NEVER projects:

- **The issue identifier** (the `<TEAM>-<NUMBER>` code such as `ABC-142`) — it
  identifies this source document, not a project.
- **The issue title** or any rephrasing of it — it describes the work, not a project.
- **The URL slug** at the end of the issue URL — it's a URL path derived from the title.
- **Code identifiers** — class names, module names, function names, tool names,
  variable names, CLI subcommands. Technical vocabulary the issue talks ABOUT, not
  workstreams.
- **Abbreviations or acronyms** treated as named systems (e.g. `API`, `CI`, `CD`, or
  other technical-abbreviation-style identifiers used throughout the body) — not
  projects.
- **Work themes or body section headings** — multi-word phrases describing what the
  issue is about ("architecture refactor", "caching layer", "observability substrate").
  Those are the subject of the work, not a project.
- **Other issue identifiers** referenced in the body (links to related issues) — they
  are other source documents in this same table.

If you are tempted to extract something from the body as a Project — **don't**. The body
describes the work for the metadata Project; it does not name separate projects. Any
Project beyond the metadata value is a false positive.

The only time to extract a non-metadata Project is when the body unambiguously names a
different workstream owned by a different team or customer — and the onboarding block
confirms it's a real entity in this deployment's world. When in doubt, skip. The
curator consolidates duplicates cheaply; false Project nodes are harder to clean up.

### What IS worth extracting beyond the metadata Project

- **People in comments or description** — @-mentions, assignees, or people named as
  active participants (e.g. "Alex is reviewing", "Handed off to Sam"). Create as
  `Person` entities with AFFILIATED/contributor facts to the metadata project.
- **Commitments and blockers** from the description or comments. "Blocked on the
  vendor's API key" → ASSERTED/blocker fact. "Targeting end of Q2" →
  ASSERTED/commitment fact. Fact text must be a direct quote or close substring.

That is the complete list of what to extract from a Linear issue beyond its metadata
Project. Anything else is body text and does not become a graph node.

### Illustrative examples and hypotheticals are NOT facts

Issue descriptions often contain illustrative examples, sample scenarios, or
hypothetical quotes used to explain a design problem. These are teaching material
inside the document, not real facts about real entities.

Signals that a passage is illustrative and must be IGNORED for extraction:

- Leading phrases like `Example:`, `e.g.`, `For example`, `Imagine`, `Suppose`,
  `Hypothetical:`.
- Quoted passages inside the body that describe a scenario rather than report an event.
- Inline code blocks showing sample input/output.
- Lists framed as "what the extractor might see" or "what could go wrong" —
  metadiscussion, not live facts.

Do not create entities or facts from illustrative content. The onboarding block lists
any fixture / test-dataset names that must always be skipped regardless of how they
appear.

### Issue change records (source_type: linear_change)

When the record is an issue change (indicated by "Change:" in the content):

- **One change = at most one TRANSITIONED fact.** A status change from "In Progress" to
  "In Review" → TRANSITIONED/status_change with fact text describing the transition.
- **Reference the person who made the change** if named in "Changed by: …".
- **Don't create new entities from structured fields.** Issue, project, person are
  already known from the parent issue. Reuse the same names.
- **Keep it minimal.** A change record yields at most one or two facts.

### Source timing

The fact's `source_at` is the issue's `linear_created_at` or the change's `changed_at` —
never the indexing time.
