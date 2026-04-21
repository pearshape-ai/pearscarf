## Linear extraction guidance

Linear records come in two shapes — issues and issue changes. **Neither is an entity in the graph.** They are source documents — they contain facts and references to entities that you should extract, but the record itself never becomes a graph node. The record is provenance for what you extract, not a subject.

### Issue records (source_type: linear)

When the record is an issue (indicated by "Issue:" prefix in the content):

- **Never create an entity for the issue itself.** Do not create a `Project` (or any other) node named after the issue title, identifier (e.g. "PEA-126"), or a sub-task description. The issue is the source of facts, not the subject of them.
- **Never treat other issue identifiers as projects.** References to parent or related issues (e.g. "PEA-121", "PEA-125") are other records in this same table. They are not projects. Skip them.
- **Don't re-extract structured fields.** The assignee, status, priority, project, and labels are already stored as structured data in the issues table. They are passed to extraction as context, not as the substance to extract from. Focus extraction on the description and comments — that's where unstructured knowledge lives.
- **Extract people mentioned in comments.** Comments often reference people by first name or @-mention. Extract them as person entities when they're actively involved ("@Sarah can you review this?" → person Sarah with AFFILIATED/contributor fact to the project).
- **Extract commitments and blockers from comments.** "Blocked on Acme's API key" → ASSERTED/blocker fact. "Pushing to next sprint" → ASSERTED/commitment fact about timeline.
- **Extract genuinely distinct project references.** Only when the description or comments mention a named initiative that is clearly separate from the issue's own Linear project — e.g. "coordinating with the billing team on this" → `Project: billing team` if not already in graph. The issue's own Linear project is already in metadata; don't re-create it. When unsure, skip.
- **Source timing.** The fact's `source_at` should be the issue's `linear_created_at`, not the time PearScarf indexed it.

### Issue change records (source_type: linear_change)

When the record is an issue change (indicated by "Change:" in the content):

- **One change = at most one TRANSITIONED fact.** A status change from "In Progress" to "In Review" → TRANSITIONED/status_change, from the project entity, to null, fact text describes the transition.
- **Reference the person who made the change.** If "Changed by: Michael Chen", extract or reference the person entity.
- **Don't create new entities from structured fields.** The issue, project, and person are already known from the parent issue extraction. Reuse the same entity names.
- **Keep it minimal.** A single change record should produce at most one or two facts. Don't over-extract.
- **Source timing.** The fact's `source_at` should be the change's `changed_at` timestamp, not the indexing time.
