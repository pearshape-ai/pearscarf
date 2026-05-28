# AGENTS.md

This file is the entrypoint for AI coworkers connecting to a PearScarf graph.

PearScarf is the **horizontal context** that lets a team of AI coworkers
coordinate and collaborate — a shared operational graph that holds what
shipped, happened, was decided, and is currently true. Every coworker in the
workforce works from the same view of reality, coordinating not by messaging
each other but by reading and writing the same graph: what one coworker ships
becomes what another announces and what another grounds its pitch in, without
any hand-off.

It is not per-agent memory. It's the shared truth across coworkers.

## How to use it (the surface)

Connect to a PearScarf MCP endpoint and you get:

- **`recall`** — natural-language search across the graph's facts. Your first call.
- **`get_entity_context`** — full picture of a named entity.
- **`query_facts`** — parameterized graph queries (subject, edge, fact_type, time).
- **`get_fact_history`** — supersession timeline for a single fact.
- **`get_record_status`** — check whether a freshly-submitted record finished indexing.
- **`submit_record`** — write back: persist the body to your records store, then
  call this with the resolvable URL.

The full read discipline is served live at the **`pearscarf://guide/consumer`**
MCP resource — fetch it once at session start.

## Two things that matter

- **Current truth by default.** Stale facts are filtered out unless you ask.
  Use `get_fact_history` when you need history.
- **Provenance is non-negotiable.** Every fact has a `source_url` pointing back
  to its record. When you submit, the body must already be persisted at that URL.

PearScarf itself ships as `pearscarf` — see `README.md` for self-hosting, and the
`CHANGELOG.md` for what's in this version.
