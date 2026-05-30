# Roadmap

This document expands the roadmap section in `README.md`.

PearScarf is the **horizontal coordination layer for AI workforces** — a shared operational graph where agents ground, decide, and hand off work. The list below is directional, not promised; priorities shift as we operate real workforces grounded here.

We value community involvement. The easiest contributions today are extraction-quality improvements, eval datasets, and reference integrations for foreign agents. For roadmap-level work, please open an issue before starting — we want contributor energy to land where it can help.

## Milestones

### ✅ Operational graph — provenance and temporal correctness

PearScarf records every fact with the source it came from and the time the fact applies to, separately from when the system learned about it. Nothing is silently overwritten; older assertions stay queryable. The full history of what the system knew and when is preserved.

### ✅ Entity resolution

Surface forms — *"Michael"*, *"M. Chen"*, *"michael@acme.com"* — collapse to the same canonical entity when the system is confident, and defer to a human when it isn't. Aliases accumulate over time without merging the wrong things.

### ✅ Intent system — executor and coordinator types

PearScarf treats *intents* as first-class — planned work with owners, roles, dependencies, and statuses, persisted alongside records but skipping extraction. The same graph that holds reality holds the planned-action layer workforces coordinate through.

### ✅ MCP query and write surface

Any MCP-compatible agent connects directly: structured queries for facts, entities, records, and intents; structured writes for records and intents. Two hundred tokens of grounded context instead of ten thousand of raw scrollback.

### ✅ Workforce coordination patterns

Multi-agent runs ground in the same operational graph. One agent ships, another announces grounded in that ship, another publishes — all coordinating through records and intent dependencies rather than direct messages between agents.

### ✅ Eval pipeline

Extraction quality is measured against ground-truth corpora on every change. Regressions are visible across versions; the bar can be moved deliberately, not by accident.

### ⚪ Benchmark and eval — coordination-level

The current eval covers per-fact correctness. The next stretch is workforce-level: did the agents coordinate cleanly, hand off correctly, ground their claims, avoid stepping on each other. Benchmarks comparing workflows grounded in PearScarf against workflows that aren't.

### ⚪ Verification and augmentation

An asynchronous loop that resolves write-path conflicts, seeks corroboration to upgrade uncertain facts toward confirmed, enriches entity records with missing detail, and escalates the genuinely irresolvable. Never blocks ingestion; keeps the self-improvement work off the critical path.

### ⚪ Multi-agent backbone

The longer arc. PearScarf as the coordination protocol for agents in any runtime, in any language, anywhere — records pushed in through a standard surface, context queried out by agents that have never seen each other. The intent system already coordinates handoffs; broader interop and parallel-coordination hardening are next.

### ⚪ More agent interfaces

Today agents reach PearScarf through MCP. There are agents and workflows that don't speak MCP yet, and there are surfaces beyond synchronous read/write — events, subscriptions, push. Broadening the connection surface is the path to *any agent in any stack can ground here*.

### ⚪ Graph correction

Humans say *"that's wrong"* and the system acts on it: the fact is invalidated, the correction is recorded with provenance, and the pattern feeds back into future extraction. The graph learns from being wrong.

## Design principles

- **Provenance.** Every fact traces back to its source record. *Where did this come from* is always answerable.
- **Temporal transparency.** Nothing silently overwritten. Newer truth supersedes older without losing either.
- **Human control.** Human-in-the-loop at every uncertain boundary. The system asks when it isn't confident.
- **Observability.** Every extraction, every graph write, every query is traced. The system shows its work.
