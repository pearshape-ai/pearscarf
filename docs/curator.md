# Curator

The Curator is a standalone async worker that runs after each record is indexed. Its job is to make the graph reality-aligned over time. It is not a ground-truth authority — it is a best-effort cleanup pass that improves graph quality without blocking the write path.

## What it does

### AFFILIATED semantic dedup
Collapses semantically equivalent AFFILIATED edges across records. When multiple records describe the same organizational role with different wording (e.g. "VP Eng" and "VP of Engineering"), the older edge is staled and the most recent survives. Genuinely distinct roles (e.g. employee and advisor at the same company) coexist.

### ASSERTED semantic dedup
Collapses semantically equivalent ASSERTED facts — same claim, different wording. The equivalence bar is high: false positives (wrongly collapsing distinct claims) are worse than false negatives. Genuinely distinct claims (e.g. two separate commitments about different deliverables) coexist.

### Expired commitment detection
Stales ASSERTED[commitment] and ASSERTED[promise] facts where `valid_until` has passed with no subsequent resolution. This is mechanical — no LLM needed. Expired commitments are staled with `replaced_by=null` since there is no successor edge.

### Confidence upgrades
Upgrades surviving edges from `inferred` to `stated` when merged source records include a source that explicitly stated the fact. Runs both per-slot (after a dedup collapse) and globally (catching edges that were never collapsed but gained a `stated` source through literal dup merging).

## How it runs

Follows the same worker loop pattern as the indexer: poll `curator_queue`, claim one entry, process inline, delete entry, repeat. One entry at a time — no concurrency.

The processing order per cycle:
1. AFFILIATED dedup (record-scoped)
2. ASSERTED dedup (record-scoped)
3. Expired commitment scan (global)
4. Confidence upgrade scan (global)

## Triggering

The indexer enqueues `record_id` in `curator_queue` after `_mark_indexed` succeeds. The Curator never touches records where `indexed=false`.

## Crash recovery

Abandoned claims (where the Curator crashed mid-processing) are detected by timeout and reset on the next cycle. Default timeout: 10 minutes (`CURATOR_CLAIM_TIMEOUT`).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CURATOR_POLL_INTERVAL` | `30` | Seconds between poll cycles |
| `CURATOR_CLAIM_TIMEOUT` | `600` | Seconds before an abandoned claim is reset |

## Intended limitations

- **Internal only** — no external API calls, no HIL, no expert agents.
- **Semantic dedup uses an LLM judge** — it may miss equivalences or produce false positives, especially on ASSERTED facts. False positives (wrongly collapsing distinct claims) are worse than false negatives — the judge prompt is calibrated accordingly.
- **Expired commitment detection is mechanical** — it stales on deadline expiry regardless of whether the commitment was actually fulfilled. A completed commitment without a TRANSITIONED[completion] edge will appear expired. The Augmentation agent (future) handles resolution confirmation.
- **The `_notify_expiry` hook is a no-op** — future HIL/agent notification is reserved but not yet implemented.
- **Equal `source_at` conflicts are left unresolved** — logged but not acted on. The Augmentation agent (future) resolves these with external corroboration.
- **The Curator never deletes** — it only sets `stale`, `replaced_by`, and `confidence`. History is always preserved.
