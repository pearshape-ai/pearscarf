# Changelog

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
- `ps memory entity` shows temporal info: `[was]` marker on superseded facts, `(since ...)` on current ones
- `ps memory graph` shows current vs total fact counts when they differ
- `ps memory record` shows temporal info on facts and relationships
- `retrofit_temporal()` migration function sets `valid_at = created_at` on pre-existing data
- `scripts/retrofit_temporal.py` — one-time migration script for upgrading from pre-1.7.0

## 1.6.4
- Print `PearScaff vX.Y.Z` version banner on startup for `ps run` and `ps discord`

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
- `pearscaff expert linear` standalone command for direct interaction
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
- Added `neo4j` Python driver dependency and `pearscaff/neo4j_client.py` connection module
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
- Added extraction prompt testing utility (pearscaff extract-test / scripts/test_extraction.py)
- Runs extraction prompt against stored emails, prints results — no writes to graph or vector store
- Supports single record, multiple records, or all relevant emails
- LangSmith tracing support when enabled

## 1.3.0
- Extracted all system prompts from Python code into standalone markdown files under pearscaff/prompts/
- Added prompt loader utility (pearscaff.prompts.load)
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
- Memory inspection CLI: `ps memory list/search/entity/graph/record`
- `ps memory list -f` — tail-style real-time memory watching
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
- pearscaff gmail --auth command for OAuth setup

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
- Versioning (ps --version)
- REPL UX improvements

## 0.3.0
- Session-based async communication via SQLite
- Terminal REPL with session management
- Discord bot with thread-per-session mapping

## 0.2.0
- Worker agent with reasoning and task routing

## 0.1.0
- Gmail expert agent (headless browser, reads emails, marks as read)
