# Curation

Curation is a Consumer that runs after each record is processed by Extraction. Its job is to make the graph reality-aligned over time. It is not a ground-truth authority — it is a best-effort cleanup pass that improves graph quality without blocking the write path.

## What it does

### Expired commitment detection
Stales ASSERTED[commitment] and ASSERTED[promise] facts where `valid_until` has passed with no subsequent resolution. Mechanical — no LLM needed. Expired commitments are staled with `replaced_by=null` since there is no successor edge.

### Confidence upgrades
Upgrades edges from `inferred` to `stated` when the edge's accumulated `source_records` include at least one with `confidence=stated`. A global scan runs each cycle.

### Supersession detection
For each new edge written by the just-extracted record, finds non-stale sibling edges sharing the same `(from_id, edge_label, fact_type)` — same subject, same kind of claim. `to_id` is deliberately not required to match, so day-different supersession is caught (e.g. an old commitment to `Day(2026-05-04)` vs a new commitment to `Day(2026-05-05)` for the same subject).

From `{new edge} ∪ {siblings}`, the **authoritative** edge is the one with latest `source_at` (when the source event happened in the world); ties break to `recorded_at`, then `created_at`. This handles out-of-order record arrival — a record dated May 4 landing after a May 5 record means the May 5 sibling is authoritative regardless of processing order.

The authoritative edge plus the other siblings are passed to an LLM judge (prompt at `pearscarf/knowledge/curator/judge.md`). The judge returns per-sibling `superseded` / `coexist` decisions with reasons. Each `superseded` sibling is staled with `replaced_by = authoritative.edge_id`.

The judge call uses the deployment's configured `MODEL` (same as extraction). One LLM call per new edge with siblings; no cap on sibling count for v1 — bounded in practice because records emit 1–3 edges each and only same-slot siblings are passed in. Per-call sibling count + decisions are logged for cost visibility.

The judge never marks the authoritative edge stale — even if it tries to (defensive guard).

## What it no longer does

Semantic dedup (AFFILIATED and ASSERTED) used to live here. It was removed when the extractor agent became capable of deduping at write time: the agent now reads the graph through its tools before saving, so equivalent edges are not written in the first place. See PEA-116 for candidate future actions if dedup drift reappears.

## How it runs

Same Consumer pattern as Extraction and Triage: poll `curator_queue`, claim one entry, process inline, delete entry, repeat. One entry at a time — no concurrency.

Per cycle:
1. Expired commitment scan (global)
2. Confidence upgrade scan (global)
3. Supersession scan (scoped to the just-processed record's edges; calls LLM judge per edge with siblings)

## Triggering

Extraction enqueues `record_id` in `curator_queue` after `_mark_indexed` succeeds. Curation never touches records where `indexed=false`.

## Crash recovery

Abandoned claims (where Curation crashed mid-processing) are detected by timeout and reset on the next cycle. Default timeout: 10 minutes (`CURATOR_CLAIM_TIMEOUT`).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CURATOR_POLL_INTERVAL` | `30` | Seconds between poll cycles |
| `CURATOR_CLAIM_TIMEOUT` | `600` | Seconds before an abandoned claim is reset |

The env variable names retain the `CURATOR_` prefix — the Postgres queue table is `curator_queue`, and the env vars match the table name. The consumer class is `Curation`; the channel it drains is `curator_queue`.

## Intended limitations

- **Internal only** — no external API calls, no RIL, no expert agents. (The LLM judge in supersession is the one exception: it calls the deployment's configured `MODEL` through `pearscarf.agents.llm_client`. No new vendor surface.)
- **Expired commitment detection is mechanical** — it stales on deadline expiry regardless of whether the commitment was actually fulfilled. A completed commitment without a TRANSITIONED[completion] edge will appear expired. Resolution confirmation is future work (see PEA-33).
- **The `_notify_expiry` hook is a no-op** — future RIL notification is reserved but not yet implemented.
- **Supersession is per-record only for v1.** It runs scoped to the just-processed record's edges. A periodic global supersession sweep (across all entities, independent of new arrivals) is a separate v2 feature; design notes for a future `psc curation sweep` CLI command live alongside this implementation.
- **Supersession uses heuristic sibling selection + LLM judgment.** Siblings are selected mechanically on `(from_id, edge_label, fact_type)`. The judge call is the only LLM-based decision; it can be wrong. When in doubt the prompt biases toward `coexist` to avoid staling true facts.
- **Curation never deletes** — it only sets `stale`, `replaced_by`, and `confidence`. History is always preserved.
