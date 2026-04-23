# PearScarf Roadmap — Engineering

> For the current user-facing version of this roadmap, see [roadmap.md](roadmap.md). For the previous user-facing version, see [roadmap-v1.md](roadmap-v1.md).

## What it is

PearScarf is a context engine for agent teams. It ingests operational records from data sources via expert agents, runs LLM-powered extraction into a temporal knowledge graph, and exposes a read-only query surface via MCP. The graph captures entities (Person, Company, Project, Event) connected by typed, directed fact-edges (AFFILIATED, ASSERTED, TRANSITIONED), each carrying full provenance and bi-temporal timestamps.

The goal: a shared memory layer for multi-agent systems that improves itself over time without blocking the write path.

---

## What's done

**Temporal knowledge graph** — entities and fact-edges in Neo4j. Three edge labels cover the operational world: organizational attachments (AFFILIATED), claims and assertions (ASSERTED), and observed state transitions (TRANSITIONED). Every fact carries `source_at` (event time), `recorded_at` (transaction time), `confidence`, `source_record`, and `stale`/`replaced_by` pointers. Nothing is deleted — facts are staled and replaced, history preserved.

**Bi-temporal modeling** — two independent timestamps on every fact-edge. `source_at` derives from the record's own timestamp (email sent date, issue `created_at`, change `changed_at`). `recorded_at` is when PearScarf indexed it. Records arriving out of order land at the correct point in the factual timeline regardless of processing order.

**Entity resolution** — handled inline by the extraction agent via read-only graph tools (`find_entity`, `search_entities`, `check_alias`, `get_entity_context`). The agent looks up candidates in the graph during extraction and decides match-or-new before writing. IDENTIFIED_AS self-edges accumulate confirmed aliases; deduplicated via MERGE on surface form. Uncertainty surfacing for low-confidence decisions is future work (see PEA-11).

**Expert plugin architecture** — self-contained expert packages in `experts/`. Each expert owns a connect module (API client + tools), an ingester (background polling loop), and knowledge files (agent prompt, extraction guidance, entity types, record schemas). Manifest declares source type, record types, schema paths, and entry points. Registry builds runtime indexes from DB on startup; falls back to filesystem scan. `ExpertContext` is the single interface experts receive — `StorageProtocol`, `BusProtocol`, `LogProtocol`, config dict, and expert name. No pearscarf internals imported by experts. Three experts ship: gmailscarf, linearscarf, githubscarf.

**Curation** — Consumer polling `curator_queue`. Two passes per cycle: expired commitment detection (`valid_until < today`) and confidence upgrades (`inferred` → `stated` when a `stated` source record exists in `source_records`). Semantic dedup happens at write time via the extractor agent's graph tools rather than as a curation pass. Never deletes.

**MCP server** — FastMCP over HTTP/SSE. Read-only. Seven tools: `find_entity`, `get_facts`, `get_connections`, `get_relationship`, `get_conflicts`, `get_open_commitments`, `get_open_blockers`. Named API key auth. `context_query.py` is the shared read layer used by both the retriever agent and the MCP server.

**Install pipeline** — 7-stage validation (package locatable, manifest valid, knowledge contract, entry points importable, conflict checks, identifier pattern validation, eval dataset). DB writes on install: `experts`, `entity_types`, `identifier_patterns`, `expert_record_schemas`. Typed tables created from JSON Schema declarations in manifest. Lifecycle commands: install, enable, disable, uninstall, update.

**Eval framework** — graph-based pipeline: ingest → index → query graph → score. Two subcommands: `psc eval er` (entity resolution: merge recall, false merges, node count) and `psc eval facts` (fact extraction precision/recall/F1 per edge label). Temporal accuracy and noise rejection where applicable. Versioned results: `(dataset_version, pearscarf_version)`.

---

## In progress

**Entity resolution quality** — the architecture is correct; prompt performance on real data is not yet good enough. Edge cases: first-name-only mentions, role-based references ("the VP of Engineering"), cross-record name variations, companies with subsidiary/brand name ambiguity. Requires a name-variations eval dataset and iterative prompt work against it. This is the highest-leverage work in the system — entity fragmentation is a compounding failure.

---

## What's next

**Extraction quality iteration** — prompt changes against the base scenario eval dataset, regression testing on every change. Per-label F1 as the primary signal. Tightening the extraction → curator → eval loop so changes can be validated quickly.

**Cross-source entity resolution** — same entity referenced with different naming conventions across Gmail, Linear, and GitHub. Requires the resolver to use source context and cross-record signals, not just within-record surface form matching. Depends on name-variations eval dataset.

**Session-aware messaging** — AgentRunner currently clears message history per invocation. Sessions should persist across turns with bounded context window (summarize or truncate older turns).

**Bus replacement** — Postgres polling at 1s intervals is the bottleneck for real-time behavior. NATS is the leading candidate: native request/reply, persistent streams (JetStream), any-language clients. Required before external agent protocol is viable.

---

## Horizon

**Verification and augmentation agent** — async agent outside the write path. Resolves equal-`source_at` conflicts (two current facts for the same slot). Upgrades `inferred` → `verified` via external corroboration (LinkedIn, web search). Enriches entity records with missing data. Flags irresolvable cases for HIL. This is the self-improvement loop.

**Graph correction loop** — natural language correction ("that's wrong") → worker invalidates edge, records correction, verification agent learns from it. Requires audit log of every graph mutation.

**Ontology agent** — HIL for uncertain entity types and fact categories. Updates extraction prompts from feedback. Runs evals to verify no regression. The system learns what matters in a given deployment.

**External agent protocol (NATS)** — out-of-process expert agents registering via a standard protocol. Records pushed over NATS subjects, agent-to-agent messaging via request/reply. Enables experts in any language, any framework. PearScarf becomes pure memory infrastructure.

**Pip-installed expert SDK** — `pearscarf` published to PyPI with a stable `pearscarf.sdk` surface. Semver guarantees on `ExpertContext` protocols. Enables third-party expert authors.

**Agents generating agents** — agent that creates a new expert package from a data source description. The system expands its own capabilities.