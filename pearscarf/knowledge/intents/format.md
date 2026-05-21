# PearScarf intent format

**Format version:** 0.1.0

This spec describes the body shape of an intent submitted to PearScarf via the MCP `submit_intent` tool. Intents are *committed plans* — what the team or an agent intends to do, in plain prose. They are persisted but do not reach the graph; the graph is for reality only. Mutable per-intent state (status, parent, type) lives on the `intent_details` sidecar table and is changed via `set_intent_*` tools.

## What an intent is for

An intent captures a commitment to act. It is not a fact, not a record of something that happened — it is the operator's or an agent's plan, queued for someone to pick up. Each intent moves through a small lifecycle: **todo → in_progress → done** (or **cancelled**), with status flipped explicitly via `set_intent_status`.

Two non-negotiable rules apply to every intent:

1. **Committed, not exploratory.** An intent is something you commit to doing — not a brainstorm, not a "we might want to look into this," not a wish. If you're thinking out loud, draft elsewhere. Submitting an intent means a downstream consumer (agent, orchestrator, operator) can pick it up and act on it.

2. **One outcome per intent.** A single intent commits to a single observable outcome. If the work has two distinct deliverables — e.g. *"ship the feature"* and *"draft the announcement"* — submit two intents. Compose them into a hierarchy via `parent_record_id` if they belong under the same epic.

## Body shape

The body is plain markdown prose. There is no required header structure — intents are not parsed for fields. The discipline is in the prose itself.

### Title convention

**The first non-empty line of the body is the intent's title.** Keep it short (≤ 120 chars), single-sentence, actionable — it's what surfaces in dashboards, list views, and any operator scan over open work. Write it like a commit header: the change in one clean phrase. Everything below the title line is the agent's pickup brief; agents read the whole body (including the title line) as their task. No artificial section headers are required between title and body.

A well-formed intent body addresses, in this order:

- **What (title line)** — the intended outcome in one sentence. This is the first non-empty line and becomes the surfaced title.
- **Who** — the role or agent owning the work. Omit for containers (intents that exist only to group sub-intents).
- **Why** — one sentence on motivation. Skip if the parent intent makes it obvious.
- **Acceptance** — the observable reality fact that means done. Phrase it as something an outside reader could verify after the work lands.

### Author discipline

- **One outcome.** Each intent commits to one observable outcome. Decompose epics by submitting sub-intents with `parent_record_id`.
- **Concrete acceptance.** State done-ness in terms an outside reader could verify after the work lands — not *"system feels stable"*.
- **Detail liberally.** Unlike reality records (which capture atomic facts for cross-domain consumers), an intent is *pickup instructions* for an agent or operator about to act. Give them what they need to succeed — links, file paths, prior context, function names, ticket IDs, internal jargon native to the work. The body's job is to set the picker-upper up to act, not to be readable across the whole graph.

## Submit-time fields

Pass alongside the body via the MCP `submit_intent` tool:

- **`parent_record_id`** *(optional)* — the intent id of a parent intent, making this a sub-intent. The intent must exist and have been submitted with op_area=intent. Null / omitted means top-level.
- **`intent_type`** *(optional)* — dispatch lifecycle: `"executor"` (default; runs once, completes) or `"coordinator"` (parent of children; wakes when its children complete to re-evaluate against the goal). Immutable after submit. Use `"coordinator"` only when the intent will dispatch sub-intents and needs to wake on their completion; otherwise omit and accept the `"executor"` default.
- **`runtime`** *(optional)* — which orchestrator adapter dispatches this intent. Default `"claude"`. Other values (`"codex"`, `"hermes"`, etc.) are registered orchestrator-side; PearScarf stores the string opaquely. Free-form; no enum.
- **`runtime_config`** *(optional)* — JSON object the orchestrator passes through to the runtime adapter unchanged. Keys depend on the runtime (for `"claude"`: e.g. `chrome_required`, `mcp_servers`, `model`, `prompt_role`). PearScarf doesn't interpret the contents — it just persists and surfaces them.
- **`owner`** *(optional)* — specific agent identity that should pick up this intent (e.g. `"hex"`). The orchestrator uses this for routing.
- **`owner_role`** *(optional)* — role tag describing the *function* the agent serves (e.g. `"head-eng"`, `"sre"`). Survives swapping individual agents; the orchestrator can match any agent in that role when `owner` is unset.
- **`depends_on`** *(optional)* — list of other intent ids that must reach status `done` before this intent is eligible for dispatch. Forms a DAG. Cycles are rejected. Missing referent intents are rejected. Default: empty.
- **`set_by`** *(optional)* — who's submitting (agent name, operator handle). Stored on the sidecar audit field; surfaced in `query_intents` and `get_intent`.

## What PearScarf does on receipt

1. Validates the body is non-empty.
2. If `parent_record_id` is set: confirms the parent exists and is an intent. Rejects otherwise.
3. Atomically inserts a `records` row (op_area=intent, indexed=true, classification=relevant — so it skips triage and extraction) and an `intent_details` row with `status='todo'` and the provided parent / type / set_by.
4. Returns `{intent_id, status: "todo"}`.

## Lifecycle

Status transitions happen via `set_intent_status` — there is no scheduled or automatic transition. The expected loop:

- **todo** — submitted, not yet picked up.
- **in_progress** — an agent or operator has taken ownership and is acting.
- **done** — the observable acceptance has been met. Convention: the agent that completes the work submits a reality record describing what happened *and* flips the intent status to done; this is two operations, not one.
- **cancelled** — the intent has been abandoned. The body of a follow-up intent or a reality record can capture why; the cancellation itself is just the status flip.

## Linking reality to intent

A reality record (submitted via `submit_record`, op_area=reality) may optionally include a body line:

```
closes: <intent-id>
```

This is *evidence* that the reality record fulfills the intent. It does not auto-flip the intent's status; status flips remain explicit via `set_intent_status`. The line is human/agent-readable provenance for the orchestrator and reviewers.

There is no `cancels:` convention — cancellation is a status flip.

## Examples

### Leaf intent (a task)

```
Implement the op_area=intent submission surface in pearscarf.

Who: hex.
Why: agents need a dedicated MCP tool that creates the sidecar state row
atomically — submit_record is reality-only.

Acceptance: pearscarf 1.36.0 ships submit_intent, query_intents,
get_intent, get_intent_tree, set_intent_status, set_intent_parent;
integration tests cover the surface; benchmark suite still reports
100% on er-foundations.
```

Submit-time: `intent_type="executor"` (default; this is a leaf task), `set_by="hex"`. Omit `parent_record_id` if top-level; pass the epic's intent id if it belongs under one.

### Container intent (a milestone)

```
Ship the AI-coworker demo on the orchestrator + pearscarf foundation.
```

That's it — milestones describe the outcome and let sub-intents carry the detail. Submit-time: `intent_type="coordinator"` (because this intent will dispatch sub-intents and needs to wake on their completion). Sub-intents (implement / deploy / announce / post) each carry `parent_record_id` pointing at this coordinator's intent id, and default to `intent_type="executor"`.
