# Curator

The Curator is a standalone async worker that runs after each record is indexed. Its job is to make the graph reality-aligned over time. It is not a ground-truth authority — it is a best-effort cleanup pass that improves graph quality without blocking the write path.

## What it does

### Expired commitment detection
Stales ASSERTED[commitment] and ASSERTED[promise] facts where `valid_until` has passed with no subsequent resolution. Mechanical — no LLM needed. Expired commitments are staled with `replaced_by=null` since there is no successor edge.

### Confidence upgrades
Upgrades edges from `inferred` to `stated` when the edge's accumulated `source_records` include at least one with `confidence=stated`. A global scan runs each cycle.

## What it no longer does

Semantic dedup (AFFILIATED and ASSERTED) used to live here. It was removed when the extraction agent became capable of deduping at write time: the agent now reads the graph through its tools before saving, so equivalent edges are not written in the first place. See PEA-116 for candidate future actions if dedup drift reappears.

## How it runs

Follows the same worker loop pattern as the indexer: poll `curator_queue`, claim one entry, process inline, delete entry, repeat. One entry at a time — no concurrency.

Per cycle:
1. Expired commitment scan (global)
2. Confidence upgrade scan (global)

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
- **Expired commitment detection is mechanical** — it stales on deadline expiry regardless of whether the commitment was actually fulfilled. A completed commitment without a TRANSITIONED[completion] edge will appear expired. Resolution confirmation is future work (see PEA-33).
- **The `_notify_expiry` hook is a no-op** — future HIL notification is reserved but not yet implemented.
- **The Curator never deletes** — it only sets `stale`, `replaced_by`, and `confidence`. History is always preserved.
