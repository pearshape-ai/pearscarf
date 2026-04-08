Every fact has an `edge_label` (the relationship type) and a `fact_type` (the specific kind within that label). Pick the combination that most precisely describes the relationship or claim.

### AFFILIATED — organizational attachments

Stable facts about how entities relate. Who belongs to what, who leads what. Rarely change over time.

`fact_type` values: `employee`, `contractor`, `advisor`, `board_member`, `founder`, `investor`, `legal_counsel`, `consultant`, `owner`, `contributor`, `reviewer`, `stakeholder`, `subsidiary`, `sub_project`, `other`

- `employee` — person is employed at or professionally affiliated with a company. Ongoing role, not a one-off interaction. "Michael is VP Engineering at Acme", email domain implies employment.
- `founder` — person started or co-founded a company. Explicitly stated as founder or co-founder.
- `owner` — person leads, owns, or is responsible for a project or workstream. Implies ongoing accountability. "Sarah is leading the integration."
- `contributor` — person participates in a project or team but doesn't lead it. "Michael is on the integration team."
- `subsidiary` — company is a division of another company. "AWS is a division of Amazon."
- `sub_project` — project belongs to a company or parent project. "the Acme API integration" (project affiliated with Acme).
- `advisor` — person advises a company or project in an ongoing capacity.
- `investor` — person or company has an investment relationship.
- `legal_counsel` — person or company provides legal representation.
- Use `other` when the affiliation is clear but doesn't match any specific type.

Don't use AFFILIATED when: person just interacted with the company, bought something from them, or attended their event. Don't use for event attendance.

### ASSERTED — claims, commitments, evaluations, decisions

Things that were said, promised, decided, or observed. Business facts with temporal significance.

`fact_type` values: `commitment`, `promise`, `decision`, `evaluation`, `opinion`, `concern`, `blocker`, `request`, `update`, `risk`, `goal`, `reference`, `other`

- `commitment` — a promise, deadline, agreement, scheduled obligation. "Demo scheduled for Thursday", "agreed to deliver the API spec by Friday", "contract renews March 2026."
- `decision` — a choice was made. "Decided to go with AWS over GCP", "board approved the budget."
- `blocker` — something is blocked, delayed, or dependent. "Integration blocked on Acme's API key", "can't proceed until legal reviews."
- `evaluation` — actively considering or reviewing. "Evaluating switch to AWS", "reviewing vendor proposals."
- `update` — a status or progress report. "Pipeline processing is back to normal."
- `concern` — a worry or risk raised. "Worried about timeline slippage."
- `risk` — an identified risk. "SOC2 certification may delay launch."
- `reference` — entity meaningfully referenced but connection doesn't fit other types. Use sparingly — if another type fits, use it.
- Use `other` when the assertion is clear but doesn't match any specific type.

Don't use ASSERTED when: it's a vague intention with no concrete commitment — "we should meet sometime."

### TRANSITIONED — observed state changes

Something moved to a new state. Status transitions, priority changes, role changes, completions.

`fact_type` values: `status_change`, `stage_change`, `role_change`, `ownership_change`, `resolution`, `completion`, `cancellation`, `other`

- `status_change` — moved to a new status. "Moved to In Review", "priority escalated to Urgent."
- `completion` — something was finished. "Integration completed", "deal closed."
- `cancellation` — something was cancelled. "Demo cancelled", "project shelved."
- `role_change` — person changed roles. "Sarah promoted to VP."
- Use `other` when the transition is clear but doesn't match any specific type.

Don't use TRANSITIONED when: describing a current static state with no evidence of change.

### Do not use

`IDENTIFIED_AS` — reserved for the system's entity resolution process. Never output this.
