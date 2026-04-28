## op_area inference

This record arrived without an explicit `op_area` marker on its metadata. Decide one as part of triage and emit it via the `classify` tool's `op_area` field.

- `reality` — facts that have happened or are observed: a shipped change, a stated event, a current state, a completed action.
- `intention` — facts about what should or will happen: objectives, plans, commitments, design proposals not yet acted on.

When in doubt, prefer `reality`. Only choose `intention` when the record is unambiguously about future or planned work.
