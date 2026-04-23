# Changelog

## 1.26.10
- Fold the Retriever's tools into the Assistant and delete the Retriever entirely. The five read-only tools previously owned by the Retriever expert (`SearchEntitiesTool`, `FactsLookupTool`, `GraphTraverseTool`, `DayLookupTool`, `VectorSearchTool`) move to a new top-level module `pearscarf/graph_query_tools.py` and register directly in `Assistant._build_agent`'s tool registry. No more bus hop or dedicated process for context queries — the Assistant runs the graph/vector lookups itself. The Assistant's own redundant `SearchEntitiesTool` (the graph-direct variant) is removed in favor of the richer `context_query`-backed version.
- Delete the Retriever machinery: `pearscarf/experts/retriever.py`, `pearscarf/knowledge/retriever/agent.md`, and the `retriever` entry in `pearscarf/knowledge/__init__.py`'s prompt registry. The retriever's tool-selection + edge-label + temporal-marker guidance is absorbed into `pearscarf/knowledge/assistant/agent.md` so the Assistant knows when to use which graph tool.
- Delete `pearscarf/agents/runner.py` (the `AgentRunner` class). `ExpertBot(SessionConsumer)` replaced it for expert bus agents in 1.26.9; the retriever was the last user and is gone now. Matching cleanup in `startup.py`: `SystemComponents.runners` list dropped; retriever wiring and `AgentRunner` import removed. Dead `create_ingest_expert_for_runner` factory in `experts/ingest.py` also removed.
- Docs + assets updated: `docs/architecture.md` (file tree + startup flow + prose), `docs/context_query.md` (consumers renamed from retriever to graph_query_tools), `docs/expert_guide.md` (AgentRunner → ExpertBot), `docs/eval-metrics.md`, `docs/roadmap-eng.md`; `docs/assets/architecture-system.svg` replaces the "Retriever" box with "Graph tools (in Assistant)"; `docs/assets/retriever-query-flow.svg` deleted.
- No infra / compose changes — Retriever was never its own container.

## 1.26.9
- Migrate expert bus agents from `AgentRunner` to a generic `ExpertBot(SessionConsumer)`. Extract the session-caching + history-rebuild + per-message dispatch logic that `Assistant` was carrying into a new `pearscarf/session_consumer.py` → `SessionConsumer(Consumer)` base; `Assistant` now inherits from it and only declares its tools + prompt. New `pearscarf/expert_bot.py` → `ExpertBot(SessionConsumer)` — one class, no per-expert subclasses. Each enabled expert with a `knowledge/agent.md` gets an `ExpertBot` instance at startup configured with that expert's tool list + domain prompt; the instance shadows the class-level `name` with its `expert_name` so it polls the correct bus target. Replace the three `AgentRunner(expert.name, factory, bus)` call sites in `startup.py` with `ExpertBot(...)` invocations; `SystemComponents` gets an `expert_bots: list` field and `stop_system` stops them. `AgentRunner` is retained in-tree for the retriever only and dies with the Retriever in 1.26.10. No container / compose changes — expert bots continue to run inside the existing `discord` container via `start_system(bot_only=True)`. Docs (`architecture.md` file tree + session prose) updated to match.

## 1.26.8
- Rename the Worker to `Assistant` and subclass it from `Consumer`. Polling wrapper becomes a `Consumer` subscribed to `messages WHERE to_agent='assistant'`; inner LLM agent becomes a named `AssistantAgent(BaseAgent)` subclass. Consumer hooks: `_next` polls the bus for its `to_agent` and buffers a batch, draining one at a time; `_handle` loads the session history, routes per-session to a cached `AssistantAgent` instance, and runs the agent. Per-session agent caching + logging-callback wiring that used to live in `AgentRunner` for the worker case now lives inside `Assistant`. Bus target rename `worker` → `assistant` across every writer (`interface/discord_bot.py`, `interface/repl.py`, and the `send_message` tool description). Module `pearscarf/agents/worker.py` → `pearscarf/assistant.py`. Knowledge subdir `knowledge/worker/` → `knowledge/assistant/`; prompt registry key `worker` → `assistant`; prompt content updated ("You are the assistant…"). Added `psc assistant start` CLI command (standalone runner, analogous to `psc extraction start` / `psc triage start`). Docs (`architecture.md` file tree + prose + ASCII diagram, `usage.md`, `expert_guide.md`, `roadmap-eng.md`) and SVG diagrams (`email-pipeline.svg`, `architecture-system.svg`, `retriever-query-flow.svg`) updated. Also takes out the obsolete triage-via-assistant surface that survived the PEA-137 cleanup: `ClassifyRecordTool` removed from Assistant (record classification is Triage's job — "one mouth per graph layer"); the matching "Triage:" and "Batch triage:" sections removed from the assistant prompt; unused `store.classify_record()` helper dropped; the `docs/expert_guide.md` ingester example rewritten from the old `ctx.bus.send(to_agent='assistant', "New issue ...")` shape to a `Consumer`-subclassed ingester that writes records via `connect.ingest_record(...)` with no bus hop. Breaking: any external bus writer still sending `to_agent='worker'` won't be picked up; any importer of `pearscarf.agents.worker.create_worker_agent` or `pearscarf.storage.store.classify_record` breaks.

## 1.26.7
- Consolidate consumer and tool layouts into top-level modules before Phase 3. The single-file packages `pearscarf/extraction/`, `pearscarf/triage/`, `pearscarf/curation/` collapse into top-level modules `pearscarf/extraction.py`, `pearscarf/triage.py`, `pearscarf/curation.py` — dropping the stuttering import path `pearscarf.extraction.extraction` etc. The expert registry (`pearscarf.extraction.registry`) moves to `pearscarf.registry` since it's not extraction-specific — it's imported from experts/ingest.py, interface/cli.py, interface/install.py, interface/startup.py, expert_context.py, knowledge/__init__.py, eval/runner.py. The shared read-only graph tools (`FindEntityTool`, `SearchEntitiesTool`, `CheckAliasTool`, `GetEntityContextTool`) move from `pearscarf.extraction.extraction_tools` to `pearscarf.graph_access_tools` at the top level; they're used by both Triage and Extraction. `SaveExtractionTool` is Extraction-specific and moves inline into `pearscarf.extraction` alongside `Extraction` and `ExtractorAgent`. The `pearscarf/tools/` package flattens to `pearscarf/tools.py` (just `BaseTool` + `ToolRegistry`); the legacy `math.py` + `web_search.py` tool implementations and the now-dead `ToolRegistry.discover()` auto-registration mechanism (with its `registry.discover()` call sites in `worker.py` and `cli.py`) are deleted. Docs (`docs/architecture.md` file tree + prompt-composition section) updated to match. Breaking for any external import of `pearscarf.extraction.*`, `pearscarf.triage.triage`, `pearscarf.curation.curation`, or `pearscarf.tools.{math,web_search}`.

## 1.26.6
- Refactor the three expert ingesters (`gmailscarf`, `linearscarf`, `githubscarf`) to `Consumer` subclasses: `GmailIngest(Consumer)`, `LinearIngest(Consumer)`, `GithubIngest(Consumer)`. Each replaces its bespoke `while True` + `time.sleep(interval)` daemon thread with the inherited poll-loop plumbing from `Consumer`. `_next()` buffers a batch from the external API and drains one item at a time; `_handle(item)` calls the existing per-record ingest functions on the connect instance. `LinearIngest` and `GithubIngest` keep their initial/incremental sync distinction via a `_synced_at` field — the first cycle does the bulk initial load inline (no per-item `_handle` pass) and sets `_synced_at`; subsequent cycles buffer updated items and process them through `_handle`. Per-expert `<EXPERT>_POLL_INTERVAL` env vars remain the polling-cadence source of truth (defaults `300s`); per-instance `poll_interval` constructor kwarg still overrides. Module-level `start(ctx)` is kept as a thin wrapper so the `ExpertDefinition.start(ctx)` contract in `extraction/registry.py` is unchanged — it creates the consumer, calls `.start()`, and returns the underlying thread. No manifest / CLI / startup changes; ingesters still boot via `psc dev --poll` or `psc expert start-ingestion <name>`.

## 1.26.5
- Rename `Curator` to `Curation` and subclass it from `Consumer`. Consumer hooks: `_setup` calls `init_db`; `_next` runs `_reset_timed_out_claims` (crash recovery) then atomically claims the oldest `curator_queue` entry; `_handle` calls `_process` and deletes the entry (or releases the claim and re-raises on exception so Consumer's base logs + continues). The `log_fn` / `_print` pattern is dropped — `Curation` logs to session logs via `log.write` like `Extraction` and `Triage`. `Curation.default_poll_interval` is pulled from the existing `CURATOR_POLL_INTERVAL` env var (default `30s`); the per-instance `poll_interval` constructor kwarg still overrides. Module `pearscarf/curation/curator.py` → `pearscarf/curation/curation.py`. CLI `psc curator start` / `psc curator status` → `psc curation start` / `psc curation status`; `startup.py` component attr `curator` → `curation`; eval runner's `curator` variable → `curation`. The `curator_queue` Postgres table keeps its name (schema identifier, renaming would require a migration). Config env var names `CURATOR_POLL_INTERVAL` / `CURATOR_CLAIM_TIMEOUT` keep their names so infra env files don't break. Docs updated: `docs/curator.md` → `docs/curation.md` with content refreshed; `architecture.md`, `data-model.md`, `roadmap-eng.md`, `ril-design.md`, `usage.md` prose updated; `mcp_server.py`'s `get_conflicts` tool description updated. SVG diagrams in `docs/assets/` caught up at the same time — `email-pipeline.svg`, `write-path.svg`, `architecture-system.svg` now show `Extraction` / `Curation` instead of `Indexer` / `Curator`. Breaking for anything that runs `psc curator start` or imports `pearscarf.curation.curator.Curator`.

## 1.26.4
- Rename the triage polling wrapper class from `TriageAgent` to `Triage`, and subclass it from `Consumer`. The inner LLM agent becomes a named `TriageAgent(BaseAgent)` subclass with fixed `agent_name='triage_agent'`, parallel to `ExtractorAgent`. Consumer hooks: `_setup` calls `init_db` + `_reset_stale_triaging` (crash recovery); `_next` atomically claims the oldest `pending_triage` record; `_handle` runs `_process` and releases the claim on exception so the record retries. Module `pearscarf/triage/triage_agent.py` → `pearscarf/triage/triage.py`. Module-level `TRIAGE_POLL_INTERVAL = 5` becomes `Triage.default_poll_interval = 5.0` (overridable via constructor kwarg). The `log_fn` constructor param is dropped — `Triage` logs to session logs via `log.write` like `Extraction`. CLI `psc triage start` unchanged; `startup.py` imports and instantiation updated; `docs/architecture.md` file-tree and classification section updated. Breaking for anything that imports `pearscarf.triage.triage_agent.TriageAgent` as the polling wrapper — the class at that name now refers to the LLM agent subclass.

## 1.26.3
- Rename `Indexer` to `Extraction` and subclass it from `Consumer`. The bespoke poll/thread/lifecycle plumbing is removed; `_next` returns one unindexed relevant record at a time (buffering batches from the DB) and `_handle` calls the existing `_process_record` pipeline. One-shot `init_db` + `graph.ensure_constraints` moves into `_setup`. The inner BaseAgent becomes a named `ExtractorAgent(BaseAgent)` subclass with fixed `agent_name='extractor_agent'`. Directory `pearscarf/indexing/` → `pearscarf/extraction/`; the class module `indexer.py` → `extraction.py`; sibling modules (`registry.py`, `extraction_tools.py`) move with it. Knowledge subdir `pearscarf/knowledge/indexer/` → `pearscarf/knowledge/extractor/`; prompt file `extraction_agent.md` → `extractor_agent.md`; registry key `extraction_agent` → `extractor_agent`. CLI `psc indexer start` → `psc extraction start`; `startup.py` component attr `indexer` → `extraction`; eval runner updated. Docs (`architecture.md`, `usage.md`, `curator.md`, `data-model.md`, `expert_guide.md`, `eval-metrics.md`, `ril-design.md`) and `README.md` refreshed to match. SVG diagrams under `docs/assets/` still show "Indexer" and will be updated in a later documentation pass. Breaking for anything that imports `pearscarf.indexing.*` or runs `psc indexer start`.

## 1.26.2
- Introduce `pearscarf.consumer.Consumer` — abstract base for channel consumers. Subclasses implement `_next()` (poll one message) and `_handle(msg)` (process it); the base class owns the poll loop, daemon-thread lifecycle (`start` / `stop` / `run_foreground`), and sleep cadence between empty polls. An optional `_setup()` hook runs once before the loop starts (for e.g. `init_db`). `poll_interval` is configurable per consumer via constructor kwarg, with a `default_poll_interval` class-level fallback so each subclass can carry its own natural cadence. No existing runners are touched — this commit only introduces the base class.

## 1.26.1
- Remove dead Anthropic client and its supporting imports from `Indexer.__init__`. `self._client = anthropic.Anthropic(...)` was never referenced; extraction routes through `BaseAgent` via `_run_extraction_agent`. Also drops the unused `import anthropic` and the four unused `pearscarf.config` imports (`ANTHROPIC_API_KEY`, `EXTRACTION_MAX_TOKENS`, `EXTRACTION_MODEL`, `EXTRACTION_TEMPERATURE`) from the module. No behavior change.

## 1.26.0
- Remove the legacy triage-via-worker path from all three ingesters (`gmailscarf`, `linearscarf`, `githubscarf`). They used to end `ingest_record` with `ctx.bus.send(to_agent="worker", ...)` asking "is this relevant?" — a leftover from before the triage agent existed. Records now land with `classification=pending_triage` and the triage agent picks them up via queue polling. Restores the cost-safety assumption that disabling the workers profile means no triage LLM spend. Begins the `1.26.x` agent-architecture series.

## 1.25.8
- Tighten the base `project` entity definition. Drops the loose "workstream" framing that let work-tickets match too easily. The new definition anchors the concept with "a project is the thing work happens *for*, not the work itself" and extends the do-not-extract list with explicit negatives: tasks / tickets / issues / bugs / PRs / commits / meetings (which are records of work, not projects), code repositories, and generic technologies or product categories without a named context. Core vocabulary files intentionally avoid naming expert-contributed types (like `repository`, which only exists when githubscarf is installed) — negative rules stay principled so the LLM picks from whatever vocabulary it actually has in the current install. Complements `1.25.7`'s linearscarf-side tightening — this one affects every extractor since `project` is a base type shared across experts.

## 1.25.7
- Tighten linearscarf extraction prompt so Linear issues are treated as facts, not entities. `experts/linearscarf/knowledge/extraction.md` now explicitly tells the extractor "never create an entity for the issue itself" and "never treat other issue identifiers as projects." The open-ended "extract project references" rule is tightened to "only extract genuinely distinct named initiatives; when unsure, skip." Resolves the failure mode where Linear issues were being extracted as `Project` nodes because `Project` was the closest-fitting base type and the prompt encouraged broad project extraction. Reflects the principle that entities are things with evolving state over time; issues are work-unit snapshots — therefore facts, not entities. No data-model change; no new entity types; no code changes.

## 1.25.6
- `docs/mcp-clients.md` — new operator guide for wiring an MCP client (Claude Code, Claude Desktop, custom) to PearScarf. Covers prerequisites, per-client setup (CLI + JSON config), generic SSE shape, verification probe, and rotation. Complements `docs/mcp_tools.md` (tool reference) — the new doc is the "how do I connect" side, the existing one is the "what tools exist" side. README + `mcp_tools.md` link to it.

## 1.25.5
- Rename the Discord monolith entrypoint and add a decomposed Discord service. The bare `psc discord` command (which used to boot the full monolith with Discord as its frontend) is now `psc dev` — name matches its actual purpose (local-dev all-in-one). `psc discord` is now a group with a single subcommand, `psc discord start`, that runs only the bot + bus-coupled agents (worker, retriever, expert agents) — indexer / curator / triage / MCP are expected to run in their own containers. `start_system()` gains a `bot_only` kwarg that gates the queue-worker / MCP startup; `run_bot()` passes it through. Dockerfile CMD updated from `psc discord --poll` to `psc dev --poll`. Breaking: `psc discord --poll` no longer works; use `psc dev --poll` for local dev or `psc discord start` for the decomposed service.

## 1.25.4
- Make the expert CLI pluggable. Per-expert Click groups (`gmail`, `linear`, `github`) and their subcommands are gone — they hardcoded expert names and used the wrong names at that (expert is `gmailscarf`, not `gmail`). Replaced with generic verbs that take the expert name as an argument: `psc expert auth <name>` and `psc expert start-ingestion <name>`. Breaking: `psc expert gmail auth` is now `psc expert auth gmailscarf`; `psc expert gmail start-ingestion` is now `psc expert start-ingestion gmailscarf`; same pattern for linear and github. Auth is dispatched by convention — if an expert's `tools_module` exports a `run_auth_flow` function, `psc expert auth <name>` invokes it; otherwise it errors cleanly. The `run_oauth_flow` function in gmailscarf renamed to `run_auth_flow` to match. Adding a new expert no longer requires editing `cli.py`.

## 1.25.3
- `psc expert <name> start-ingestion` — run one expert's ingester standalone in the foreground. Available for `gmail`, `linear`, `github`. Wraps the existing `ExpertDefinition.start(ctx)` path (same code `psc discord --poll` uses inline) and blocks the main thread until Ctrl+C. Each ingester can now be started / stopped / tuned independently — an expert's OAuth failing no longer takes the whole runtime down, and per-expert polling cadence via env files (e.g., `GMAIL_POLL_INTERVAL`) is now actionable by running only the experts you want. Closes Phase 1 of the runtime decomposition.

## 1.25.2
- Convert per-expert commands (`gmail`, `linear`, `github`) from flag-commands to groups, so each can grow its own subcommands cleanly. `psc expert gmail --auth` is now `psc expert gmail auth` (breaking). `psc expert linear` and `psc expert github` become groups (`github` is new — the other two existed as placeholder commands). Top-level `psc gmail --auth` shortcut removed — redundant with `psc expert gmail auth`, undocumented, and asymmetric (no `psc linear` / `psc github` equivalents). Docs updated. Sets up the `start-ingestion` subcommand in the next commit.

## 1.25.1
- `psc triage start` — run the triage agent standalone in the foreground. Same pattern as `psc indexer start` / `psc curator start`. Triage is the relevance classifier that moves records from `pending_triage` to `relevant` / `noise` / `uncertain`; making it its own entrypoint gives an independent cost kill-switch for LLM classification alongside the indexer's kill-switch for LLM extraction.

## 1.25.0
- `psc indexer start` — run the indexer standalone in the foreground. Wraps the existing `Indexer` class with a signal-safe main-thread loop, mirroring the pattern already used by `psc curator start` and `psc mcp start`. First step toward running the pearscarf runtime as separately-controllable processes — the monolithic `psc discord --poll` path is unchanged and continues to boot the indexer inline as before.

## 1.24.1
- Fix `psc expert gmail --auth` — it was reading `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` from the top-level `pearscarf.config` module, but those settings moved to per-expert env files (`env/.gmailscarf.env`) in an earlier refactor. The flow now loads the expert env file directly and reads the credentials from the environment, matching how the runtime client is configured.

## 1.24.0
- Project released under the MIT License. Added `LICENSE`, `CONTRIBUTING.md`, and license metadata in `pyproject.toml` (`license`, `classifiers`, `readme`). Contributions require signing a CLA (administered via [cla-assistant.io](https://cla-assistant.io/)) before first merge — the CLA grants the project a broad license to contributed code, preserving relicensing optionality while keeping the current license MIT.

## 1.23.0
- Dockerfile + compose service for the pearscarf app. `docker compose up -d` brings up the full stack — Postgres, Qdrant, Neo4j, and pearscarf running `psc discord --poll` by default. Single-stage build on `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`, `tini` for PID 1 signal handling.
- Container entrypoint waits for Postgres to be reachable, then installs each expert under `experts/` idempotently before booting the app. First-start scaffolds the DB registration; subsequent starts detect already-installed experts via `psc expert list` and skip them.

## 1.22.0
- Expert manifests declare `relevancy_check: skip | required`; `skip` auto-marks records relevant on save, restoring the indexer hand-off for the three shipped experts after the stalled worker-side-triage migration.
- Triage pipeline — `required` experts classify noise internally via a hard filter and leave the rest for a new triage agent that grounds its LLM decision in onboarding, per-expert `relevancy.md` guidance, and read-only graph context; gmail is the first consumer.

## 1.21.0
- Onboarding — a single markdown file that onboards PearScarf to the world it operates in (team, vocabulary, what matters), injected into the extraction prompt and overridable via `ONBOARDING_PROMPT_PATH`.

## 1.20.2
- Dead code cleanup across the paths that architectural migrations left behind. The old single-shot extraction, the three-way entity resolution judge, the blocking HIL flow (`resolution_pending` / `resolution_status`), the curator's LLM dedup prompts, and the pre-packaging Gmail/Linear prompt folders are all gone. No behaviour change — none of it was on a live execution path.
- Pytest harness removed — it was a safety net during the architecture migration and no longer tests current behaviour. `psc test` command and pytest dev dependency dropped alongside. `psc integration-test` (smoke test for context_query tools) stays.
- One-time migration scripts removed (`migrate_sqlite_to_postgres.py`, `retrofit_temporal.py`, `extract_test.py`) — all artefacts of past transitions, not used in the current flow.
- Docs updated to reflect current reality: indexer uses the extraction agent inline for ER; curator does expiry + confidence upgrade only; knowledge tree no longer lists removed folders.

## 1.20.1
- Curator simplified — LLM-based semantic dedup removed. Extraction agent now handles dedup at write time by checking existing AFFILIATED facts. Curator retains expiry scanning and confidence upgrades (both deterministic, no LLM calls).
- Extraction agent prompt updated to skip duplicate AFFILIATED facts when the same affiliation already exists in the graph.

## 1.20.0
- Curator starts automatically with `psc run` and `psc discord`. Prints processing status to terminal — record being processed, remaining queue count, staled duplicates, expired commitments, confidence upgrades.
- `psc eval facts` — fact extraction eval with curator processing. Scores non-stale facts against structural ground truth (precision, recall, F1).
- Legacy eval runner removed.

## 1.19.8
- `psc eval facts` — fact extraction eval with curator processing. Ingests records, waits for indexer + curator to finish, scores non-stale facts against ground truth. Reports precision, recall, F1, missing and extra facts.
- Legacy eval runner removed.

## 1.19.7
- Extraction agent replaces separate extraction + resolution pipeline. Single agent with read-only graph tools handles both in one reasoning loop. Validation layer checks structural integrity and fact grounding before committing.
- Seed aliases processed through the extraction agent — `## aliases` section creates IDENTIFIED_AS edges via the same commit path. Separate `_commit_seed` for seed records.
- Seed guidance prompt added (`knowledge/ingest/seed_guidance.md`). Agent prompt moved to `knowledge/indexer/extraction_agent.md`.
- Token usage tracked per record and reported in eval results.
- Debug captures full agent conversation regardless of success/failure.
- Linear issue comments included in content sent for extraction.

## 1.19.6
- Eval sequence is now self-contained — each entry specifies file path (relative to dataset) and record type. No more data_map in dataset.yaml. Seed records are just another sequence entry with `type: seed`. Dataset folder renamed `data/` → `records/`.

## 1.19.5
- Extraction prompt decomposed into ordered components. Entity types and normalization now appear before facts and edge labels. Prompt assembly order: intro → entity types + normalization → fact structure → edge labels → what to ignore → output format → source-specific guidance.
- Gmail extraction guidance updated: sender and recipient always extracted as entities (previously skipped if not mentioned in body).
- Anthropic SDK retries on 429/500/529 with exponential backoff (max_retries=3) across all LLM calls.
- ER scoring split into merge recall (per surface form) and entity merge rate (all-or-nothing per entity).
- Debug output uses dedup_key for folder names and groups by dataset version + timestamp.

## 1.19.3
- Debug mode for eval (`psc eval er --dataset <path> --debug`). Dumps full LLM prompts and responses to `{dataset}/debug/{timestamp}/` — extraction system/user prompts, extraction responses, resolution prompts and judge responses per entity. Eval now starts its own indexer instance.

## 1.19.2
- Verbose mode for ER eval (`psc eval er --dataset <path> -v`). Shows per-entity surface form resolution status after each timeslice and globally — which forms resolved correctly, which created spurious nodes, which weren't found.

## 1.19.1
- New eval runner built from scratch. Old runner preserved as `runner_legacy.py`. Reads `dataset.yaml` for config and `sequence.yaml` for deterministic record ordering. Ingests records one at a time, waits for indexer between each.
- ER scoring: node count accuracy, merge recall, false merge rate — scored against `er_ground_truth.json`. Global metrics always, timeslice metrics when present.
- `psc eval` is now a command group with subcommands. `psc eval er --dataset <path>` runs ER only. Bare `psc eval --dataset <path>` runs all available eval types.

## 1.19.0
- Eval runner resolves `dedup_key` from ground truth to actual record ID for graph scoring — compatible with uuid-based record IDs.
- `psc expert ingest --type` accepts any string instead of a hardcoded list. Record types are dynamic — defined by installed experts.

## 1.18.0
- Expert Encapsulation complete. Three experts (gmailscarf, linearscarf, githubscarf) running against the new contract — manifest-driven install, ExpertContext, typed tables, layered prompt composition. Zero expert-specific code in pearscarf core.
- Built githubscarf from scratch as the first greenfield expert. Introduces the `repository` entity type, `github_pr` and `github_issue` record types, GitHub REST API tools and polling ingester.
- Linearscarf record types prefixed: `issue` → `linear_issue`, `issue_change` → `linear_issue_change`. Avoids collision across experts.
- Record IDs now use `{type}_{uuid4_short}` (e.g. `email_3f2a1b4c`) instead of sequential counters. Globally unique, no DB query per save.
- Removed hardcoded email/issue/issue_change tables from db.py — experts own their schemas via typed tables created at install time.

## 1.17.19
- Fixed connection pool deadlock: `init_db()` was called on every DB operation, grabbing a separate connection for DDL while another held row locks. Now runs once at startup. Pool configured with non-blocking open and connect timeout to fail fast instead of hanging.
- Cleaned up DB schema — all `ALTER TABLE` migration statements folded into clean `CREATE TABLE` definitions.
- `psc expert ingest --record` now loads expert connects in-process (standalone command, not connected to running system) and marks ingested records as `relevant` so the indexer picks them up.
- Fixed worker prompt routing — expert names updated from old `gmail_expert`/`linear_expert` to actual package names (`gmailscarf`/`linearscarf`).
- Fixed `SaveEmailTool` passing metadata dict as positional `content` arg to `save_record`, causing a psycopg type error.

## 1.17.18
- Generic ingester startup via manifest. `Expert.start()` now takes `ExpertContext` instead of raw `MessageBus` — the ingester module's `start(ctx)` receives the full expert contract (storage, bus, log, config). Renamed `connector_module`/`connector_path` to `ingester_module`/`ingester_path` on the Expert dataclass.
- Env loading split by owner. Pearscarf core config loads from `env/.env` (Gmail/Linear vars removed from config.py). Expert credentials load from `env/.<name>.env` via `build_context()`, which populates both `ctx.config` and `os.environ`.

## 1.17.17
- Centralized startup sequence into `pearscarf/interface/startup.py`. Both `psc run` (REPL) and `psc discord` now call `start_system()` / `stop_system()` instead of duplicating ~100 lines of boot logic each. Fixes stale shutdown references left over from the pre-encapsulation era.
- Expert LLM agents now start automatically at boot for any expert with tools and a `knowledge/agent.md` prompt. Each gets an `ExpertAgent` wired to the expert's tool registry via a closure factory to avoid loop-variable capture.

## 1.17.16
- Restructured gmailscarf to the new expert layout. `connector/` folder deleted. Replaced by `gmail_connect.py` (API client + tools stub) and `gmail_ingest.py` (ingestion loop stub). Manifest updated to v0.1.1 with `tools:` and `ingester:` fields replacing `connector:`. Registry and install validator accept both legacy and new manifest fields.
- Removed all expert-type switches from pearscarf core. The indexer's `_build_content`, `_build_source_context`, and `_embed_record` now read from the generic `records.content` and `records.metadata` columns instead of querying per-type tables. `records` table gains a `content TEXT` column (LLM-ready formatted string, written by the expert's ingester alongside `raw`).
- Ingest tool delegates record processing to the expert via registry-cached connect instances. At startup, each expert's tools module is loaded and the connect instance is registered by record_type. No expert registered = clear error, no silent fallback.
- Eval runner loads folder-to-type mapping from `data_map.yaml` in the dataset folder instead of a hardcoded dict.
- Erase script simplified to truncate `records` + `curator_queue` only.

## 1.17.15
- Install command simplified to local-path only for MVP. Git URL and PyPI installs print a clear "not supported in this version" message. Pip install stage, pip rollback logic, and pip uninstall on lifecycle commands all removed. The validation pipeline is now 7 stages (was 8).
- `experts_dir` is configurable via `EXPERTS_DIR` env var in `config.py`, defaulting to `<repo>/experts/`. The registry reads from this config instead of hardcoding the path.

## 1.17.14
- Internal agents (worker, retriever, ingest) now receive `ExpertContext` instead of importing pearscarf internals directly. `SendMessageTool` and `ReplyTool` use `ctx.bus.send` and `ctx.log.write`. `ExpertAgent` constructor accepts `ctx` instead of raw `MessageBus`. `AgentRunner` stays on raw `MessageBus` (infrastructure, not an agent).
- `LookupEmailTool` and `LookupIssueTool` removed from the worker. These were per-record-type tools that bypassed the generic storage protocol. They'll return as generic record tools when the indexer refactor makes all records queryable through `ctx.storage`.
- `cli.py` and `discord_bot.py` now call `build_context(name, bus)` for each internal agent before constructing the agent factory.

## 1.17.13
- Added `pearscarf/expert_context.py` — the single object pearscarf hands to every expert at startup. Defines three protocols (`StorageProtocol`, `BusProtocol`, `LogProtocol`) and their concrete implementations wrapping existing pearscarf internals. Experts import only from this module — no reaching into pearscarf's storage, bus, or log packages directly. Same context for default expert agents and internal agents.
- `records` table gains `metadata JSONB`, `dedup_key TEXT`, `expert_name TEXT`, and `expert_version TEXT` columns. `save_record()` on the storage protocol writes to the generic records table with metadata as JSONB and dedup on `dedup_key`. Experts no longer need per-type tables or per-type save helpers — the generic path handles everything.

## 1.17.12
- `pearscarf run` and `pearscarf discord` now run a credential pre-flight check before starting any expert. For each enabled expert, the check reads the package's `.env.example` to learn which env vars are required (vars with empty values in the example are required; vars with non-empty defaults are optional and skipped) and verifies the operator's `env/.<name>.env` has a non-empty value for each one. On any miss, prints the expert name, the missing var, and the path to the env file to edit, then exits without starting anything. The check runs unconditionally — even without `--poll` — because the LLM agent layer can still call expert tools that need credentials.

## 1.17.11
- Added the four expert lifecycle commands: `pearscarf expert disable <name>`, `pearscarf expert enable <name>`, `pearscarf expert uninstall <name>`, and `pearscarf update <name>`. Disable and enable are reversible toggles on the active row. Uninstall prompts by default (`--yes`/`-y` to skip), removes every row for the name, and runs `pip uninstall` for non-local installs. Graph data is never touched.
- Update treats every install method the same way (local included): re-read the on-disk manifest, compare versions, and on a version change disable the currently enabled row and insert a new row with the same name and the new version. The historical row is preserved as an audit record.
- The `experts` table schema changed to support multiple versions per name. Synthetic `id` PK + `UNIQUE (name, version)`; child tables (`entity_types`, `identifier_patterns`) reference `expert_id` instead of `expert_name`. Pre-prod project: no automated migration — wipe the expert tables (or run the erase script) and re-run `pearscarf install` for any previously installed experts.
- All four lifecycle commands reset the in-process registry cache after the DB write so the next run sees fresh state.

## 1.17.10
- Added `pearscarf install <source>` — the operator-facing way to add an expert. Detects whether the source is a local path, git URL, or PyPI name, runs an 8-stage validation pipeline (pip install, package locatable, manifest valid, knowledge contract, connector contract, conflict checks, identifier patterns, eval dataset), and writes DB rows on success. Local installs skip pip entirely (the package must already be importable, typically because it lives under `experts/`).
- New entity types declared by an expert require operator approval before any DB writes happen. `--yes`/`-y` skips the prompt for non-interactive installs.
- Credential scaffolding: on a successful install, the expert's `.env.example` is copied to `env/.<name>.env` and `env/` is added to `.gitignore` if missing.
- Added `pearscarf expert list` and `pearscarf expert inspect <name>` for inspecting installed experts — name, source type, version, enabled flag, package directory, declared entity types, identifier patterns, and credential file location.
- Added `pyproject.toml` to `gmailscarf` and `linearscarf` so they can be packaged if needed. Local installs still register the package directly without invoking pip.
- New file `pearscarf/interface/install.py` owns the install command, validation pipeline, and inspect/list commands. `cli.py` just registers them on the right Click groups.

## 1.17.9
- Added Postgres tables for expert registration: `experts`, `entity_types`, `identifier_patterns`. Schema migrates non-destructively. The `experts` table is the install record (name, version, source_type, package_name, install_method, enabled); the other two are populated by the install command in a future iteration.
- Storage helpers added for the `experts` table only (`list_registered_experts`, `register_expert`, `set_expert_enabled`, `unregister_expert`). The `entity_types` and `identifier_patterns` tables exist as empty schemas — read/write surfaces will land when the install command needs them.
- Registry now reads from the DB when populated and falls back to filesystem manifest scanning when empty. `Expert.enabled` field added — DB-loaded experts honor the column, filesystem-loaded experts default to enabled. `enabled_experts()` filters accordingly.

## 1.17.8
- Expert startup is now registry-driven. `psc run` and `psc discord` no longer import any expert by name; they iterate `registry.enabled_experts()` and call `expert.start(bus)` on each. Missing credentials are skipped with a warning instead of crashing the boot.
- The per-source `--poll-email` and `--poll-linear` flags are replaced by a single `--poll` flag that brings up every enabled expert. Per-source filtering will return when enable/disable lands in the registry.
- Removed the dead `EXPERTS` shim from `pearscarf/experts/__init__.py` — discovery now belongs entirely to the registry.

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
