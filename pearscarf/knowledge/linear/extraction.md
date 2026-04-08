## Issue-specific guidance

When the record is an issue (indicated by "Issue:" prefix in the content):

- **Don't re-extract structured fields.** The assignee, status, priority, project, and labels are already stored as structured data. Focus extraction on the description and comments — that's where unstructured knowledge lives.
- **Extract people mentioned in comments.** Comments often reference people by first name or @-mention. Extract them as person entities when they're actively involved ("@Sarah can you review this?" → person Sarah with AFFILIATED/contributor fact to the project).
- **Extract commitments and blockers from comments.** "Blocked on Acme's API key" → ASSERTED/blocker fact. "Pushing to next sprint" → ASSERTED/commitment fact about timeline.
- **Extract project references.** Issues often reference other projects or initiatives in description/comments. These cross-references are high-value for the graph.

## Change-specific guidance

When the record is an issue change (indicated by "Change:" in the content):

- **Extract the transition as a TRANSITIONED/status_change fact.** A status change from "In Progress" to "In Review" → TRANSITIONED/status_change, from the project entity, to null, fact text describes the transition.
- **Reference the person who made the change.** If "Changed by: Michael Chen", extract or reference the person entity.
- **Don't create new entities from structured fields.** The issue, project, and person are already known from the parent issue extraction. Reuse the same entity names.
- **Keep it minimal.** A single change record should produce at most one or two facts. Don't over-extract.
