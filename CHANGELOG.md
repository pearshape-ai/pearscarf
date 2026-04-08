# Changelog

## 1.17.7
- Introduced the expert registry. PearScarf now discovers installed experts by scanning `experts/` and parsing each `manifest.yaml` at startup, exposing them via lookups by source type, record type, and package name.
- Layer 1 and Layer 2 of the extraction prompt are now separately constructed and independently cached. Layer 2 has a hook for entity types declared by expert manifests (no-op today, ready for when an expert ships its own entity types).
- Extraction prompt composition moved entirely into the registry. The hardcoded `record_type → source` table in the indexer is gone — Layer 3 routing now comes from each expert's manifest via a new `record_types` field.
- `KnowledgeStore` and `SaveKnowledgeTool` removed. They were a learning loop for the deprecated browser-based experts and have no role in the new architecture.

## 1.17.6
- Linear expert moved out of pearscarf into the `linearscarf` package. The Linear agent is now defined entirely by `knowledge/agent.md` — no Python factory. Connector code is split into focused files (api client, poller, writer, agent wiring, tools), and the writer ships **real** create/update/comment operations rather than stubs. The Linear LLM agent layer is offline until the registry can auto-load it.

## 1.17.5
- Gmail expert moved out of pearscarf into the `gmailscarf` package. Same shape as the future Linear move: agent defined by `knowledge/agent.md`, connector split into focused files, writer present as a stub. The browser-based Gmail path (Playwright tools, BrowserManager, `psc expert gmail --login`) is **deleted entirely** — Gmail now requires OAuth credentials. The Gmail LLM agent layer is offline until the registry can auto-load it.

## 1.17.4
- Introduced `compose_prompt(record)` — the extraction system prompt is now built per-record from cached Layer 1+2 (universal rules + entity types) plus a Layer 3 selected by record type (Gmail, Linear, or none). Ingest records keep their own complete prompt. The indexer no longer holds pre-loaded prompts; it composes per call.

## 1.17.3
- Migrated `pearscarf/prompts/` to `pearscarf/knowledge/` and split the monolithic extraction prompt into layered files under `knowledge/core/`. Other agent prompts (worker, retriever, ingest, curator, etc.) moved to agent-scoped subfolders. The prompt loader is a temporary shim that stitches the layered files together at load time, to be replaced by per-record composition.

## 1.17.2
- Created the top-level `experts/` directory and added skeletons for `gmailscarf` and `linearscarf` packages — manifests, knowledge stubs, connector stubs, eval folders. Skeletons are inert; no code moved yet.

## 1.17.1
- Restructured flat `pearscarf/` into grouped module folders by concern (`storage/`, `indexing/`, `curation/`, `query/`, `mcp/`, `interface/`, `eval/`). Root now contains only cross-cutting modules. All imports updated; behavior unchanged. Also moved the extraction-test script out of the package into `scripts/` and removed the corresponding CLI command.

## 1.17.0
- Added an integration test harness (`tests/test_harness.py`) covering the six main pipeline branches: graph write, entity resolution, Gmail extraction, Linear extraction, ingest, and curator. Available via `psc test`. The LLM is mocked; Postgres, Neo4j, and Qdrant are real. Full suite runs in ~6s.

## 1.16.1
- `get_nodes_by_source_record` now returns `valid_until` from fact edges
- `_build_extracted_from_graph` passes `stale` and `valid_until` through to scorer
- Verbose mode fixed: expected facts show `edge_label/fact_type` and `valid_until`; graph facts prefer `valid_until` over `source_at`
- Confidence warnings surfaced after each record in eval output
- Per-label F1 aggregation: `per_label_f1` dict with precision/recall/F1 per AFFILIATED/ASSERTED/TRANSITIONED
- Bug fix: `_graph_is_empty` checked `day_count` instead of `day_nodes` — eval could run on dirty graph

## 1.16.0
- `score_record` extended with per-label fact counts: `affiliated_matched/extracted/expected`, `asserted_*`, `transitioned_*`
- `score_record` adds `confidence_warnings` list — identity-matched facts with mismatched confidence (informational, does not affect scores)
- `temporal_accuracy` rewritten: supports new nested `expected_edges` format (checks `stale` + `valid_until` per edge) alongside legacy flat format
- `entity_resolution_accuracy` gains optional `extracted_facts_by_record` param and `domain_inferred` branch — checks for AFFILIATED edge from surface form to canonical entity
- `eval_runner` passes `extracted_facts_by_record` to ERA

## 1.15.6
- Documentation pass: `docs/context_query.md` (data access layer reference), `docs/mcp_tools.md` (MCP tools reference for agent developers)
- Architecture doc updated with data access diagram showing write path (Indexer/Curator) and read path (Retriever/MCP → context_query)
- `psc query <tool> [--options]` — call any context_query tool directly from CLI, no MCP auth needed
- `psc integration-test` — smoke test all context_query tools, validate response shapes
- Retriever prompt updated to match current tool surface

## 1.15.5
- MCP convenience tools: `get_open_commitments`, `get_open_blockers`, `get_recent_activity`
- `get_open_commitments` — ASSERTED/commitment with `valid_until`, optional entity scope, optional `before_date` filter
- `get_open_blockers` — ASSERTED/blocker filtered to exclude those with subsequent TRANSITIONED/resolution
- `get_recent_activity` — merges TRANSITIONED facts + ASSERTED/reference facts + Postgres email metadata, default 7-day window
- MCP query surface complete: 5 primitives + 5 convenience tools

## 1.15.4
- MCP convenience tools: `get_entity_context`, `get_current_state`
- `get_entity_context` — composes get_facts + get_connections, supports `chronological` and `clustered` formats
- `get_current_state` — AFFILIATED-only current facts

## 1.15.3
- MCP primitive tools: `get_relationship`, `get_conflicts`
- `get_relationship` — shortest path between two entities via current fact-edges
- `get_conflicts` — finds AFFILIATED slots with multiple current edges

## 1.15.2
- MCP primitive tools: `find_entity`, `get_facts`, `get_connections`
- Entity resolution pattern: tools resolve names internally via `find_entity`
- Consistent error shape: `{"error": "not_found", "name": "..."}`
- `psc mcp test <entity>` smoke test command

## 1.15.1
- MCP server bootstrap with FastMCP over HTTP/SSE
- Named API key authentication: SHA-256 hashed keys, `Authorization: Bearer <key>`
- `mcp_keys` Postgres table for key management
- `/health` endpoint (no auth required)
- `psc mcp start` (standalone foreground), `psc mcp status`, `psc mcp keys` (create/list/revoke)
- MCP server auto-starts with `psc run` and `psc discord`
- No tools registered — tool registration starts in 1.15.2

## 1.15.0
- `context_query.py` — single read-only data access layer for all context queries
- Functions: `find_entity`, `get_facts`, `get_connections`, `get_facts_for_day`, `get_path`, `get_conflicts`, `get_communications`, `vector_search`
- `graph.get_path()` — shortest path between two entities via current fact-edges
- `graph.get_conflicts()` — finds AFFILIATED slots with multiple current edges
- `store.get_communications_for_entity()` — ILIKE query on emails table
- Retriever tools rewired: all five tools call `context_query` instead of `graph`/`vectorstore` directly

## 1.14.5
- Global confidence upgrade pass in Curator: upgrades edges from `inferred` to `stated` when merged `source_records` include a `stated` source
- `source_records` schema changed from flat string list to `[{record_id, confidence}]`
- `graph.append_source_record()` now accepts `confidence` parameter
- `graph.get_inferred_multi_source_edges()` and `graph.set_edge_confidence()` added
- `psc curator status` shows upgrade-eligible and expired-pending counts
- `docs/curator.md` — full Curator agent documentation

## 1.14.4
- Curator expired commitment detection: stales ASSERTED/commitment and ASSERTED/promise edges where `valid_until` has passed
- `graph.get_expired_commitments(today)` query
- `_notify_expiry()` reserved hook (no-op)
- Expiry scan runs globally every curator cycle after dedup passes

## 1.14.3
- Curator ASSERTED semantic dedup: LLM judge for collapsing equivalent claims
- `prompts/curator_asserted.md` — high-bar equivalence prompt (false positives worse than false negatives)
- Shared `_dedup_edges()` helper extracted — AFFILIATED and ASSERTED passes use identical structure
- `_process()` runs two passes: AFFILIATED first, ASSERTED second

## 1.14.2
- Curator AFFILIATED semantic dedup: LLM judge groups semantically equivalent edges, stales older ones
- `curator_judge.py` — `judge_equivalence(candidates, edge_label)` with one LLM call per slot
- `prompts/curator_affiliated.md` — equivalence prompt for organizational affiliations
- `graph.get_edges_by_source_record()` — returns edge/entity element IDs, uses `$rid IN r.source_records`
- `graph.get_edges_for_slot()` — all current edges for a (from, label, type, to) slot

## 1.14.1
- `curator.py` — standalone worker loop mirroring indexer pattern: poll → claim → process → delete
- Claim with `FOR UPDATE SKIP LOCKED`, timeout recovery for crashed claims
- `_process()` is a stub — filled in by 1.14.2+
- `CURATOR_POLL_INTERVAL` (30s default), `CURATOR_CLAIM_TIMEOUT` (600s default)
- `psc curator start` (foreground) and `psc curator status`

## 1.14.0
- `curator_queue` Postgres table: `record_id` PK, `queued_at`, `claimed_at`
- `store.enqueue_for_curation()` — INSERT ON CONFLICT DO NOTHING
- Indexer enqueues after `_mark_indexed` (best-effort, try/except)
- `psc queue` (summary), `psc queue list`, `psc queue clear --confirm`
- `psc erase-all` and `scripts/erase_all.py` include `curator_queue` in TRUNCATE

## 1.13.3
- All downstream readers updated to new fact model field names
- `scoring.py` — match key: `edge_label` + `fact_type` + `from_entity` + `to_entity`
- `eval_runner.py` — reads `edge_label`/`fact_type`/`source_at` from graph
- `cli_memory.py` — `edge_label/fact_type`, `stale`/`source_at`, `edge_label_counts`/`fact_type_counts`
- `retriever.py` — `include_stale`, `edge_labels` param, `stale`/`source_at` temporal display
- `prompts/retriever.md` — three edge labels, `[stale]` marker, `include_stale`

## 1.13.2
- Write loop literal dup check: `graph.find_exact_dup_edge()` matches on (from, to, label, type, source_record, fact)
- `graph.append_source_record()` — appends to `source_records` list on dup merge
- `_write_fact_edge()` helper on Indexer wraps dup check + create
- `docs/data-model.md` — write loop section rewritten, staleness moved to verification agent

## 1.13.1
- Extraction prompts rewired: `category`/`valid_at` → `edge_label`/`fact_type`/`valid_until`
- Three edge labels: AFFILIATED, ASSERTED, TRANSITIONED with full fact_type lists
- Indexer `source_at` derivation per record type (received_at, linear_created_at, changed_at)
- `to_entity` resolution with degradation: unresolvable targets fall through to Day node (never skip)
- `extract_test.py` validates `edge_label`/`fact_type` against `FACT_CATEGORIES` dict

## 1.13.0
- `graph.py` refactored to new bi-temporal fact edge schema
- `FACT_CATEGORIES` — dict mapping AFFILIATED/ASSERTED/TRANSITIONED to valid fact_type values
- `create_fact_edge` — new signature: `edge_label`, `fact_type`, `source_at`, `valid_until`
- `find_existing_fact_edge` and `mark_fact_stale` (replaces `invalidate_fact_edge`)
- All read functions return `edge_label`/`fact_type`/`source_at`/`stale`/`replaced_by`
- `graph_stats` — `edge_label_counts` + `fact_type_counts`
- Callers intentionally break — fixed in 1.13.1 and 1.13.3

## 1.12.5
- IDENTIFIED_AS edge deduplication via MERGE: one edge per unique alias
- `create_identified_as_edge` checks for existing edge with same `surface_form`
- On subsequent match: updates `resolved_at`, appends `source_record` to `source_records`

## 1.12.4
- IDENTIFIED_AS self-edges written after confirmed resolution decisions
- `graph.create_identified_as_edge()` — self-edge with `surface_form`, `confidence`, `reasoning`
- Email/domain deterministic match → `confidence: stated`
- LLM match → `confidence: inferred`
- Skipped when surface form equals canonical name

## 1.12.3
- Entity resolution loop wired into indexer: real LLM decisions replace temporary fallback
- `_resolve_entity()` rewritten: no candidates → create; exact name/email/domain → use; otherwise → LLM judge
- Ambiguous entities → `resolution_pending` JSONB on records, `resolution_status` column
- Records with unresolved entities not marked `indexed = TRUE`
- `_build_source_context()` — short context string per record type for the judge
- Poll query excludes `resolution_status = 'pending'`

## 1.12.2
- `prompts/entity_resolution.md` — three-way resolution judge (match/new/ambiguous)
- `_resolve_entity_with_llm()` on Indexer — builds structured user message, calls LLM, parses JSON
- Falls back to `new` on parse failure

## 1.12.1
- `graph.get_entity_context()` — builds context package per candidate (facts + 1-hop connections)
- Indexer builds context packages for non-exact candidates, logs them

## 1.12.0
- Entity resolution candidate retrieval broadened
- `graph.find_entity_candidates()` — cascading search: exact → email → domain → first-name prefix → substring → IDENTIFIED_AS
- `_resolve_entity()` uses candidates with exact match fast path; non-exact creates new entity (pre-judge fallback)

## 1.11.5
- `scripts/erase_all.py` and `psc erase-all` — wipe all system state (Postgres, Neo4j, Qdrant)
- Confirmation prompt, counts shown before acting
- `db.close_pool()` + `atexit` handler for clean shutdown (fixes PythonFinalizationError)

## 1.11.4
- Graph-based eval replaces flat-file eval
- `psc eval --dataset <path>` — ingest seed → ingest records → wait for indexer → query graph → score
- Requires clean graph (aborts if non-empty) and running indexer
- `ParseRecordFileTool.execute()` called directly, no agent overhead

## 1.11.3
- `ParseRecordFileTool` rewritten: schema validation, folder support, all-or-nothing batch semantics
- `REQUIRED_FIELDS` / `OPTIONAL_FIELDS` per record type
- Unknown fields flagged — catches eval-format records with wrong field names

## 1.11.2
- `psc expert ingest --seed <file>` and `psc expert ingest --record <file> --type <type>`
- Non-interactive modes: single agent run, print result, exit
- Interactive REPL without flags (unchanged)
- Ingest prompt updated with mode detection and reply content spec

## 1.11.1
- Ingest expert tools fully implemented
- `ParseSeedTool` — reads .md, calls `store.save_ingest()`
- `ParseRecordFileTool` — reads JSON, routes to `save_email`/`save_issue`/`save_issue_change`, auto-classifies as relevant
- `store.save_ingest()` — writes `ingest` record with `classification='relevant'`
- Indexer `ingest` branch: `_build_content()` reads `raw`, `_extract()` uses `ingest_extraction.md`

## 1.11.0
- Ingest expert agent scaffolding
- `ParseSeedTool` and `ParseRecordFileTool` (stubs)
- `create_ingest_expert()` and `create_ingest_expert_for_runner()`
- `prompts/ingest.md` — seed mode and record mode
- `psc expert ingest` standalone command
- Expert registry updated

## 1.10.0
- `psc eval --dataset <path>` — extraction eval against dataset with scoring
- `scoring.py` — entity matching, fact matching, F1, NRR, ERA, Temporal Accuracy
- `eval_report.py` — terminal report formatter + JSON results writer
- `eval_runner.py` — dataset loader, extraction orchestrator, aggregator
- `--verbose` flag for per-record debug output
- `docs/eval-metrics.md` — scope clarification added
- Roadmap eval harness checked off

## 1.9.1
- CLI short alias changed from `ps` to `psc` — avoids conflict with macOS/Linux `ps` (process status) command
- Full `pearscarf` command unchanged
- After updating: run `uv pip install -e .` to register new entry point
- Update README with project description and details

## 1.9.0
- **Project renamed from PearScaff to PearScarf**
- Python package: `pearscaff` → `pearscarf` (all imports updated)
- CLI entry point: `pearscaff` command → `pearscarf` command (`psc` short alias)
- Postgres defaults: user/database `pearscaff` → `pearscarf` (existing installs: update `.env` and recreate DB, or keep old values in `.env`)
- Docker compose defaults updated
- All documentation, prompts, and error messages updated
- No functional changes, no schema changes, no data migration needed
- After updating: run `pip install -e .` to register new entry points

## 1.8.6
- Retriever rewired to fact-edge model: `FactsLookupTool` calls `get_facts_for_entity`, groups results by category
- `GraphTraverseTool` walks fact-edges via new `traverse_fact_edges`, supports optional category filter
- New `DayLookupTool` — queries facts anchored to a specific Day node via `get_facts_for_day`
- `traverse_fact_edges` in graph.py — replaces `traverse_graph`, walks fact-edges with category/temporal filtering, includes Day nodes in results
- `graph_stats` updated to count fact-edges by category and Day nodes
- `get_nodes_by_source_record` updated to query fact-edges instead of old Fact nodes and generic edges
- Removed dead functions from graph.py: `get_entity_facts`, `traverse_graph`, `retrofit_temporal`
- Retriever prompt rewritten with tool selection guidance, fact category explanations, and temporal marker docs
- `cli_memory.py` updated to use new graph functions

## 1.8.5
- Indexer rewired to fact-edge model: `create_fact_edge` replaces `create_edge` + `upsert_fact`
- Single-entity facts (to_entity null) anchored to Day nodes via `get_or_create_day`
- Two-entity facts written as typed edges between entity nodes
- Entity name mismatches in extraction output logged as warnings and skipped gracefully
- Removed dead functions from graph.py: `create_edge`, `invalidate_edge`, `upsert_fact`
- No retriever, memory CLI, or prompt changes

## 1.8.4
- Extraction prompt rewritten: three-array output (entities, relationships, facts) → two-array output (entities, facts with categories)
- Every fact now has `category`, `fact`, `from_entity`, `to_entity`, `confidence`, `valid_at` — unifying old relationships and facts
- 13 fact categories documented in prompt: structural, activity, claims, meta
- `extract_test.py` updated: entities listed with metadata, facts grouped by category, validation warnings for entity name mismatches and unrecognized categories
- Old format (relationships array) detected and flagged with warning
- No indexer or graph changes — extraction output not wired to graph writes yet

## 1.8.3
- Fact-as-edge model: facts are now edges between entity/Day nodes instead of separate Fact nodes
- 13 fact categories across structural (WORKS_AT, FOUNDED, MANAGES, PART_OF, MEMBER_OF), activity (COMMUNICATED, MENTIONED_IN, STATUS_CHANGED), claims (COMMITTED_TO, DECIDED, BLOCKED_BY, EVALUATED), and meta (IDENTIFIED_AS)
- `create_fact_edge` — creates a typed relationship with fact text, confidence, source, and bi-temporal timestamps
- `invalidate_fact_edge` — sets `invalid_at` on a fact-edge (history preserved)
- `get_facts_for_entity` — reads fact-edges for an entity, filterable by current/all
- `get_facts_for_day` — reads fact-edges anchored to a Day node
- Old model functions (`create_edge`, `upsert_fact`, etc.) coexist — no migration yet

## 1.8.2
- Day nodes in Neo4j — represent calendar days, will serve as endpoints for single-entity facts
- `get_or_create_day(date_str)` in `graph.py` — lazy MERGE on `(:Day {date})`, one node per calendar date
- `utc_to_local_date(utc_dt)` helper — converts UTC timestamps to local dates using configured timezone
- `ensure_constraints()` — creates uniqueness constraint on `Day.date`, called once at Indexer startup
- `TIMEZONE` config var (default `America/Los_Angeles`) — controls UTC→local date conversion for Day node assignment
- No fact→Day wiring yet — infrastructure only

## 1.8.1
- Removed legacy Postgres graph tables: `entities`, `edges`, `facts` — empty/stale since v1.2.3, graph lives in Neo4j since v1.4.0
- Removed from SQLite→Postgres migration script
- Updated `docs/architecture.md`: storage diagram shows Neo4j, Knowledge Graph section describes bi-temporal Neo4j model

## 1.8.0
- Removed `entity_types` Postgres table — dead since v1.3.2 when entity types moved to extraction prompt markdown
- Removed `list_entity_types()` from `graph.py` and its Postgres imports
- Removed `_SEED_ENTITY_TYPES` constant and seed execution from `db.py`
- Removed `entity_types` from SQLite→Postgres migration script
- Updated `docs/architecture.md` to reflect current extraction pipeline

## 1.7.0
- Bi-temporal timestamps on all graph edges and facts: `valid_at`, `invalid_at`, `created_at`, `source_record`
- Facts use invalidate-and-create instead of update-in-place — old facts get `invalid_at` set, new fact created with `valid_at`
- Same invalidation model for relationships via `invalidate_edge`
- Issue change records pass `changed_at` as `valid_at` so graph timestamps reflect when the change actually happened in Linear
- Retriever `facts_lookup` defaults to current facts; `include_superseded=true` shows full history with temporal markers
- Retriever `graph_traverse` defaults to current relationships; `include_historical=true` includes past connections
- `psc memory entity` shows temporal info: `[was]` marker on superseded facts, `(since ...)` on current ones
- `psc memory graph` shows current vs total fact counts when they differ
- `psc memory record` shows temporal info on facts and relationships
- `retrofit_temporal()` migration function sets `valid_at = created_at` on pre-existing data
- `scripts/retrofit_temporal.py` — one-time migration script for upgrading from pre-1.7.0

## 1.6.4
- Print `PearScarf vX.Y.Z` version banner on startup for `psc run` and `psc discord`

## 1.6.3
- Issue change history captured from Linear's `issueHistory` API (status, assignee, priority transitions)
- New `issue_changes` table in Postgres — each change is its own record in the SOR (type `issue_change`)
- `get_issue_history` method in LinearClient with cursor pagination, parses from/to state/assignee/priority
- Changes fetched during incremental polls only (not initial bulk load) via `_sync_issue_changes` helper
- Auto-classified as `relevant` — parent issue already triaged, changes inherit relevance
- Indexer `_build_content` for issue changes — includes parent issue context (identifier, title) + change details
- Qdrant embedding with change-specific metadata (field, changed_by, issue identifier)
- Extraction prompt updated with change-specific guidance: extract transitions as facts, reference actors, keep minimal
- Dedup on `linear_history_id` (UNIQUE) — safe across repeated poll cycles
- No bi-temporal timestamps — facts accumulate as regular Fact nodes in Neo4j

## 1.6.2
- Issues flow through the extraction pipeline — no code changes needed, the Indexer already processes all unindexed relevant records regardless of type
- Extraction prompt made source-agnostic: "emails" → "records (emails and issues)" throughout
- Added issue-specific guidance section to extraction prompt: focus on description/comments, extract people from comments, extract commitments/blockers, extract project cross-references
- Cross-source entity resolution: same person/company/project from emails and issues resolves to one Neo4j node via name + email/domain matching

## 1.6.1
- Robust Linear sync: cursor-based pagination for initial load (handles teams with hundreds of issues)
- Rate limiting: automatic retry with exponential backoff on Linear API 429 responses
- Issue comments synced as part of the issue record (`comments` JSONB column)
- Issue descriptions stored (`description` TEXT column) — both new columns with migration for existing databases
- `_build_content` for issues in Indexer — assembles title + description + metadata + threaded comments for extraction
- Qdrant embedding includes issue-specific metadata (identifier, title)
- Batch triage for initial bulk load: one session with all issues summarized instead of N individual sessions
- Worker prompt updated with batch classification instructions
- `LookupIssueTool` and `get_pending_records` now include description and comments
- No graph writes — still SOR only

## 1.6.0
- Linear expert agent with full read/write via GraphQL API
- Tools: list, get, create, update, comment, search issues — with name-to-ID resolution for teams, users, projects, labels
- `issues` table in Postgres (System of Record) with dedup/upsert on `linear_id`
- Issue polling loop (`--poll-linear`) — syncs issues from Linear, creates sessions for worker triage
- Worker system prompt updated with `linear_expert` as delegation target
- `LookupIssueTool` added to worker for stored issue lookup
- `pearscarf expert linear` standalone command for direct interaction
- Config: `LINEAR_API_KEY`, `LINEAR_POLL_INTERVAL`, `LINEAR_TEAM_ID`
- No graph/vector integration for issues (SOR only)

## 1.5.0
- Un-stubbed `vectorstore.py` — `add_record` embeds via sentence-transformers and upserts to Qdrant; `query` does semantic similarity search
- Indexer embeds email content in Qdrant after Neo4j extraction (Qdrant failures don't block indexing)
- Retriever's `VectorSearchTool` un-stubbed — semantic search across stored records with scores and metadata
- Memory CLI `search` and `list` commands un-stubbed — `search` uses Qdrant semantic search, `list` scrolls recent vectors
- `scripts/reindex_all.py` now also clears Qdrant collection (delete + recreate)
- No new dependencies

## 1.4.1
- Added `scripts/reindex_all.py` — wipes Neo4j graph and resets Postgres indexed flags for re-extraction
- Interactive confirmation required before executing
- No CLI command — standalone script only (`python scripts/reindex_all.py`)
- Indexer picks up reset records automatically on next poll cycle

## 1.4.0
- Wired extraction pipeline to Neo4j — entities, relationships, and facts now written to the graph
- Added `neo4j` Python driver dependency and `pearscarf/neo4j_client.py` connection module
- Rewrote `graph.py` from Postgres stubs to Neo4j Cypher queries
- Entity resolution: MERGE on name+label, with email match for persons and domain match for companies
- Facts stored as `Fact` nodes connected via `HAS_FACT` edges (claim, confidence, source_record, created_at)
- Dynamic relationship types via APOC (`apoc.create.relationship`)
- Indexer un-stubbed: calls Claude extraction API, resolves entities, writes to Neo4j, marks indexed
- Retriever tools un-stubbed: search_entities, facts_lookup, graph_traverse query Neo4j — vector_search stays stubbed
- Worker search_entities un-stubbed — re-enables graph-aware triage
- Memory CLI: entity, graph, record commands read from Neo4j — list/search stay stubbed (need vector search)
- Added `graph_stats()` and `get_nodes_by_source_record()` to graph.py
- No Qdrant integration, no bi-temporal timestamps, no Postgres schema changes

## 1.3.2
- Extraction API call configured for structured output: temperature 0, system/user prompt split
- Extraction instructions (extraction.md) used as system prompt; record content sent as user message
- Added EXTRACTION_MODEL and EXTRACTION_MAX_TOKENS config (defaults to system MODEL and 2048)
- Removed entity_types_block DB lookup — entity types now defined directly in the extraction prompt

## 1.3.1
- Added extraction prompt testing utility (pearscarf extract-test / scripts/test_extraction.py)
- Runs extraction prompt against stored emails, prints results — no writes to graph or vector store
- Supports single record, multiple records, or all relevant emails
- LangSmith tracing support when enabled

## 1.3.0
- Extracted all system prompts from Python code into standalone markdown files under pearscarf/prompts/
- Added prompt loader utility (pearscarf.prompts.load)
- Worker, Gmail expert (browser + MCP), Retriever, and extraction prompts are now editable without touching Python
- No prompt content changes

## 1.2.3
- Gutted data processing logic in preparation for extraction pipeline rebuild
- Indexer: polls and marks records indexed, but no LLM extraction or embedding
- Retriever: tools registered but return empty results
- graph.py: all write/read functions stubbed (except list_entity_types)
- vectorstore.py: add_record and query stubbed
- Worker triage: simplified to always ask human (no graph-based auto-classify)
- Memory CLI/REPL: commands return stub messages
- No schema, dependency, or config changes

## 1.2.2
- Migrated from SQLite to Postgres for all application data
- Connection pooling via psycopg_pool (min 2, max 10 connections)
- JSONB columns for metadata, extract_fields, and message data (auto-serialize/deserialize)
- BOOLEAN columns replace INTEGER 0/1 for read/indexed flags
- Added docker-compose.yml consolidating Postgres, Qdrant, and Neo4j services
- Added migration script: `scripts/migrate_sqlite_to_postgres.py`
- Added psycopg[binary] and psycopg-pool dependencies
- Removed sqlite3, DB_PATH config; added POSTGRES_* config vars

## 1.2.1
- Replaced ChromaDB with Qdrant as the vector store
- Qdrant connects to existing Docker container (same setup from Mem0 era)
- Same embedding model (all-MiniLM-L6-v2), now loaded directly via sentence-transformers
- Removed chromadb dependency
- Added qdrant-client dependency
- Removed CHROMA_PATH config, added QDRANT_URL
- Point IDs use deterministic uuid5 for clean string↔UUID mapping

## 1.2.0
- Removed Mem0 integration — extraction quality and visibility insufficient for operational data
- Restored SQLite facts + graph + ChromaDB as the sole storage pipeline
- Removed MemoryBackend abstraction — indexer and retriever use graph.py/vectorstore.py directly
- Removed mem0ai dependency (and transitive qdrant-client, openai, etc.)
- Removed MEMORY_BACKEND, OPENAI_API_KEY, OPENAI_MODEL, QDRANT_URL config
- Neo4j and Qdrant Docker configs retained for future Graphiti/Cognee evaluation
- Memory inspection CLI and REPL commands updated to use SQLite directly

## 1.1.3
- Mem0 LLM provider switched from Anthropic to OpenAI (Mem0's native provider)
- Removed Anthropic compatibility patches (top_p, tool_choice, tool format)
- Added OPENAI_API_KEY and OPENAI_MODEL config (default: gpt-4o-mini)
- Qdrant switched from local file-based to server (Docker) — fixes multi-process locking
- All data consolidated under `data/` directory (SQLite, ChromaDB, logs, Neo4j, Qdrant, browser state)
- Fixed Qdrant exit traceback (neutered `__del__`, explicit atexit cleanup)

## 1.1.2
- Memory inspection CLI: `psc memory list/search/entity/graph/record`
- `psc memory list -f` — tail-style real-time memory watching
- Same commands in REPL via `/memory`
- Direct Neo4j graph queries for entity lookup and stats (Mem0 backend)
- SQLite backend: entity lookup, graph stats, record-level memory tracing
- Read-only — no memory editing or deletion

## 1.1.0
- LangSmith integration for observability (opt-in)
- Hierarchical tracing: agent runs, LLM calls, tool executions, memory operations
- Traces tagged with agent name, session ID, record ID
- Cost and token tracking across all agents including Mem0
- session.log preserved as local fallback

## 1.0.0
- Mem0 integration as pluggable memory backend (Neo4j graph + vector)
- Custom extraction prompt for operational email data
- Indexer simplified: delegates extraction to memory backend
- Retriever unified: single memory_search replaces facts/graph/vector queries when using Mem0
- MEMORY_BACKEND env var for switching between mem0 and sqlite
- SQLite pipeline preserved as fallback (default)

## 0.11.1
- Roadmap restructured to high-level prose milestones
- Changelog created (this file) — factual record of completed work
- Completed-item checkboxes moved out of roadmap into changelog

## 0.11.0
- Gmail expert MCP integration (OAuth, API-based email operations)
- Email polling loop with --poll-email flag (configurable interval)
- New email notifications on Discord and REPL
- MCP as default transport when configured, headless browser as fallback
- pearscarf gmail --auth command for OAuth setup

## 0.10.0
- Roadmap and vision docs update
- Balanced vision framing (transport-agnostic expert architecture)

## 0.9.1
- Project documentation: architecture diagrams, vision, roadmap, getting-started

## 0.9.0
- Retriever agent (explicit context queries)
- Three query modes: facts lookup, graph traversal, vector search
- Structured context packages returned to worker

## 0.8.0
- HIL triage (auto-classify or ask human)
- Human context capture during triage (fed to Indexer)
- Classification override support
- All classification activity visible on Discord and REPL

## 0.7.0
- ChromaDB integration (vector embeddings with sentence-transformers)
- Indexer embeds record content for semantic search

## 0.6.0
- Knowledge graph (entities, edges, facts, entity_types registry)
- Indexer agent (background LLM extraction into graph)

## 0.5.0
- System of Record (expert-owned storage, email deduplication)

## 0.4.0
- Unified session logging (actions, tool calls, reasoning, thinking, errors)
- Versioning (psc --version)
- REPL UX improvements

## 0.3.0
- Session-based async communication via SQLite
- Terminal REPL with session management
- Discord bot with thread-per-session mapping

## 0.2.0
- Worker agent with reasoning and task routing

## 0.1.0
- Gmail expert agent (headless browser, reads emails, marks as read)
