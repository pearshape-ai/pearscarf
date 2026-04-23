# Architecture

## System Diagram

<p align="center"><img src="assets/architecture-system.svg" alt="PearScarf System Architecture" width="640"></p>

<details>
<summary>Text fallback</summary>

```
┌─────────────────────────────────────────────────────────┐
│                    Interfaces                            │
│       Discord / Terminal REPL / MCP Server (HTTP/SSE)    │
└────────────┬──────────────────────────┬─────────────────┘
             │ Postgres messages         │ context_query.py
┌────────────▼──────────────────────────┐│
│            Assistant                   ││
│   (reasoning, routing, human surface)  ││
└──┬──────┬──────┬──────┬───────────────┘│
   │      │      │      │               │
┌──▼──┐┌──▼──┐┌──▼───┐┌─▼────┐  ┌──────▼──────┐
│Gmail││Linear││GitHub││Retrvr│  │ MCP Server  │
│scarf││scarf ││scarf ││      │  │ (10 tools)  │
└──┬──┘└──┬──┘└──┬───┘└──┬───┘  └──────┬──────┘
   │      │      │       │             │
   │writes│writes│writes │reads        │reads
   │      │      │       │             │
┌──▼──────▼──────▼───────▼─────────────▼──────┐
│                  Storage                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Postgres │ │ Neo4j    │ │ Qdrant       │ │
│  │ records  │ │ entities │ │ vectors      │ │
│  │ typed    │ │ fact-    │ │              │ │
│  │  tables  │ │ edges    │ │              │ │
│  │ sessions │ │          │ │              │ │
│  └──────────┘ └──────────┘ └──────────────┘ │
└──────────────────────────────────────────────┘
        ↑ writes              ↑ writes          ↑ writes
┌───────┴──────┐     ┌───────┴──────┐   ┌──────┴──────┐
│   Triage     │────→│  Extraction  │──→│  Curation   │
│ (classify    │     │ (entities,   │   │ (dedup,     │
│  pending)    │     │  facts)      │   │  expiry,    │
│              │     │              │   │  confidence)│
└──────────────┘     └──────────────┘   └─────────────┘
```
</details>

## Expert Architecture

Experts are self-contained plugin packages that live in `experts/`. Each expert owns two-way access to a single data source (Gmail, Linear, GitHub). PearScarf loads them at startup via the registry and routes records through them at runtime. Today experts run as daemon threads inside PearScarf's process; running experts as standalone processes outside the runtime is on the roadmap.

### Expert package structure

```
experts/gmailscarf/
├── manifest.yaml          # name, version, record_types, schemas, tools, ingester
├── gmail_connect.py       # API client + tool definitions + ingest_record()
├── gmail_ingest.py        # background polling loop: start(ctx)
├── schemas/
│   └── email.json         # JSON Schema (draft-07) for the email record type
├── knowledge/
│   ├── agent.md           # LLM agent system prompt
│   ├── extraction.md      # source-specific extraction guidance
│   ├── entities/          # new entity type definitions (if any)
│   └── records/
│       └── email.md       # record type documentation
├── .env.example           # required credentials template
└── pyproject.toml
```

### ExpertContext

Every agent — expert or internal — receives an `ExpertContext` at startup. It's the entire surface area experts are given:

- **`ctx.storage`** — `save_record(type, raw, content, metadata, dedup_key)`, `get_record(id)`, `mark_relevant(id)`
- **`ctx.bus`** — `send(session_id, to_agent, content)`, `create_session(summary)`
- **`ctx.log`** — `write(agent, event_type, message)`
- **`ctx.config`** — dict loaded from `env/.<expert_name>.env`
- **`ctx.expert_name`** — the expert's registered name

Experts do not import pearscarf internals. The context is the contract.

### Startup flow

`start_system()` in `pearscarf/interface/startup.py` boots the entire system:

```
1. enforce_credentials_or_exit()     — validate env files for all enabled experts
2. For each enabled expert:
   a. build_context()                — load env/.<name>.env, create ExpertContext
   b. Load tools module              — get_tools(ctx) → connect instance, cached by record_type
   c. Start LLM agent                — if tools + knowledge/agent.md exist → AgentRunner
   d. Start ingester                 — if --poll and ingester_module exists → start(ctx)
3. Start internal agents             — retriever, assistant
4. Start extraction consumer
5. Start MCP server
```

Both `psc run` (REPL) and `psc dev` (Discord monolith) call `start_system()` then run their frontend. The decomposed Discord service `psc discord start` calls `start_system(bot_only=True)` to skip the queue workers and MCP, which run as separate services under the decomposed compose.

### Registry

The registry discovers installed experts from the `experts` DB table and builds runtime indexes. It resolves which expert owns a given source type or record type, caches connect instances for tool routing, and assembles extraction prompts.

### Extraction prompts

When the Extraction consumer processes a record, the extraction prompt is composed in this order:

1. **Agent role** — `pearscarf/knowledge/extractor/extractor_agent.md`. Behavioural prompt for the extractor agent: how to reason, how to use its graph tools, match-or-new decisions. Prompt composition lives in `pearscarf.registry`.
2. **Onboarding** — a single markdown file that onboards PearScarf to the world it will operate in (the team, the kinds of interactions, the vocabulary, what matters, what to ignore). Defaults to `pearscarf/knowledge/onboarding.md` (neutral framing shipped with the repo). Operators override by setting `ONBOARDING_PROMPT_PATH` to their own file (typically `env/onboarding.md`). See `docs/onboarding.example.md` for a template.
3. **Universal rules** — how to extract entities and facts, edge labels, output format. Shared across all record types. Lives in `pearscarf/knowledge/core/`.
4. **Entity types** — what kinds of things to look for (person, company, project, event, plus any types declared by experts like repository). Automatically includes new types when an expert is installed.
5. **Source-specific guidance** — what to extract from *this* source's records. Each expert ships an `extraction.md` that tells the LLM what matters in emails vs issues vs PRs, and what to ignore.

Order is stable-to-variable: agent role and onboarding rarely change, rules update on release, source guidance changes per expert install. Installing a new expert automatically extends what the system can extract — no manual prompt editing.

Onboarding is loaded once at startup and cached (edits require restart). Target budget: 500–1500 tokens; a warning is logged above ~2000 tokens.

### Install and lifecycle

```bash
psc install ./experts/githubscarf    # 7-stage validation, typed tables, credential scaffold
psc update githubscarf               # version bump, re-validate, preserve history
psc expert list                      # show all installed experts
psc expert disable githubscarf       # stop without uninstalling
psc expert enable githubscarf        # restart
psc expert uninstall githubscarf     # remove DB rows, keep graph data
```

## Overview

```
pearscarf/
├── storage/                # Persistence layer
│   ├── db.py               # Postgres schema + connection pool + queries
│   ├── store.py            # System of Record — generic save_record + typed tables
│   ├── graph.py            # Knowledge graph CRUD — entities, fact-edges, traversal
│   ├── neo4j_client.py     # Neo4j connection manager
│   └── vectorstore.py      # Qdrant vector storage — semantic search
├── extraction.py            # Extraction(Consumer) + ExtractorAgent + SaveExtractionTool
├── triage.py                # Triage(Consumer) + TriageAgent + ClassifyTriageTool
├── curation.py              # Curation(Consumer) — graph quality (expiry, confidence)
├── consumer.py              # Consumer base class — poll loop + lifecycle
├── registry.py              # Expert registry — discovery, prompt composition, connect cache
├── tools.py                 # BaseTool + ToolRegistry (framework)
├── graph_access_tools.py    # Read-only graph tools — shared by Triage and Extraction
├── query/
│   └── context_query.py     # Read-only data access layer for retriever + MCP
├── mcp/
│   └── mcp_server.py        # FastMCP over HTTP/SSE, 10 tools
├── session_consumer.py      # SessionConsumer — poll bus target, cache per-session agents
├── assistant.py             # Assistant(SessionConsumer) + AssistantAgent
├── expert_bot.py            # ExpertBot(SessionConsumer) — one instance per enabled expert
├── agents/
│   ├── base.py              # BaseAgent — agentic loop on Anthropic SDK
│   ├── expert.py            # ExpertAgent — domain-specialized, receives ExpertContext
│   └── runner.py            # AgentRunner — retained only for the retriever (dies with 1.26.10)
├── experts/
│   ├── ingest.py            # Ingest expert — file-based data entry (seed + JSON records)
│   └── retriever.py         # Retriever expert — context queries via context_query.py
├── expert_context.py        # ExpertContext + protocols (Storage, Bus, Log) + build_context()
├── interface/
│   ├── cli.py               # Click CLI
│   ├── install.py           # Install command, validation pipeline, lifecycle commands
│   ├── startup.py           # Shared boot sequence for run + discord
│   ├── repl.py              # Non-blocking session-aware REPL
│   ├── terminal.py          # Raw terminal I/O
│   └── discord_bot.py       # Discord bot with thread-per-session
├── knowledge/               # Layered prompts for extraction and agents
│   ├── core/                # universal extraction rules + base entity types
│   ├── ingest/              # Ingest expert prompts
│   ├── extractor/           # Extractor agent system prompt
│   ├── retriever/           # Retriever agent prompt
│   └── assistant/           # Assistant system prompt
├── eval/
│   ├── runner.py            # Eval pipeline (ER + facts)
│   ├── report.py            # Report formatter
│   └── scoring.py           # Entity/fact matching, F1, noise rejection, temporal accuracy
├── bus.py                   # MessageBus — send/receive/poll over Postgres
├── config.py                # Loads from env/.env
├── log.py                   # Shared session logger
├── status.py                # In-memory agent activity registry
└── tracing.py               # LangSmith tracing utilities
```

## Agent Communication

All agent-to-agent communication goes through Postgres. No direct function calling between agents. Each agent runs in its own thread, polling for unread messages.

- **Assistant** uses `send_message` to send to humans or experts (by package name: `gmailscarf`, `linearscarf`, `githubscarf`)
- **Experts** use `reply` to send results back to whoever requested work
- The runner never auto-replies — all outbound routing is the agent's decision

## Sessions

Every conversation is a **session** (`ses_001`, `ses_002`, ...). Messages are tagged with a session ID. `SessionConsumer` (the base under Assistant + ExpertBot) caches one agent instance per session and rebuilds message history from the DB before each LLM call.

- **Human-initiated**: human types in REPL or Discord → new session
- **Expert-initiated**: expert detects an event → creates session, notifies assistant
- **Discord**: threads map to sessions via `discord_threads` table

## Database Schema

```sql
-- Communication
sessions(id, initiated_by, summary, created_at)
messages(id, session_id, from_agent, to_agent, content, reasoning, data, read, created_at)
discord_threads(session_id, thread_id, channel_id)

-- System of Record
records(id, type, source, created_at, raw, content, metadata JSONB,
        dedup_key, expert_name, expert_version, indexed, classification,
        classification_reason, human_context)

-- Expert registration
experts(id, name, version, source_type, package_name, install_method, enabled, installed_at)
entity_types(expert_id, type_name, knowledge_path)
identifier_patterns(id, expert_id, pattern_or_field, entity_type, scope)
expert_record_schemas(expert_name, record_type, version, table_name, schema_hash, created_at)

-- Operations
curator_queue(record_id, queued_at, claimed_at)
mcp_keys(id, name, key_hash, created_at, last_used_at, revoked)
```

Expert-specific typed tables (e.g. `gmailscarf_email_0_1_3`, `linearscarf_linear_issue_0_1_4`) are created at install time from JSON schemas. Records are dual-written: generic `records` row + typed table row, joined by `record_id`.

Record IDs use `{type}_{uuid4_short}` format (e.g. `email_3f2a1b4c`).

## System of Record

- **`records`** — generic table for all record types. Every record has a `type`, `source`, `raw` (original data), `content` (LLM-ready string), `metadata` (JSONB), and `dedup_key`.
- **Typed tables** — per-expert, per-record-type, per-version. Created from JSON Schema at install. Columns match schema properties.
- **`store.save_record()`** — single write path used by all experts via `ctx.storage`. Handles dedup, ID generation, and dual-write to typed table.

### Classification

Every record carries a `classification`. The Extraction consumer only processes `classification = 'relevant'`. Policy is declared per expert in the manifest:

```yaml
relevancy_check: skip | required
```

- **`skip`** — framework auto-classifies every record as `relevant` on save. Used for internal/trusted sources (Linear, GitHub) where noise is rare.
- **`required`** — the expert is responsible for classification. In its `ingest_record`, it may run a deterministic hard filter and pass `classification="noise"` to `save_record` for unambiguous hits. Everything else is passed through without a classification; the framework then defaults it to `pending_triage` and the triage agent picks it up.

**State machine for `required` records:**
```
(ingest) → noise | pending_triage → triaging → relevant | noise | uncertain
```

The Triage consumer (`pearscarf/triage/triage.py`) polls `classification='pending_triage'`, claims atomically via `UPDATE-RETURNING` to `triaging`, and runs `TriageAgent` with onboarding + the expert's `knowledge/relevancy.md` + read-only graph tools (`find_entity`, `search_entities`, `check_alias`, `get_entity_context`). The read-only constraint preserves the extractor/triage boundary — triage can use the graph to judge relevance but never writes facts. Uncertain results sit in an RIL queue pending the human-facing path.

If an expert passes any classification value directly, the framework stores it verbatim — no policy override.

Seed records (`psc expert ingest --seed`) and manually ingested files (`--record`) bypass both paths — they're trivially relevant by construction.

## Configuration

Core config loads from `env/.env`. Expert credentials load from `env/.<name>.env` via `build_context()`.

| Variable | Default | Source |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | env/.env |
| `MODEL` | `claude-sonnet-4-5-20250929` | env/.env |
| `DISCORD_BOT_TOKEN` | (required for discord) | env/.env |
| `POSTGRES_*` | localhost defaults | env/.env |
| `NEO4J_*` | localhost defaults | env/.env |
| `QDRANT_URL` | `http://localhost:6333` | env/.env |
| `TIMEZONE` | `America/Los_Angeles` | env/.env |
| `MCP_PORT` / `MCP_HOST` | `8090` / `0.0.0.0` | env/.env |
| `ONBOARDING_PROMPT_PATH` | shipped default | env/.env |
| `GMAIL_*` | | env/.gmailscarf.env |
| `LINEAR_*` | | env/.linearscarf.env |
| `GITHUB_*` | | env/.githubscarf.env |

## Knowledge Graph

The Extraction consumer processes records into a knowledge graph. All graph data lives in Neo4j.

- **Entities** — nodes with labels (Person, Company, Project, Event, Repository). Merged on name + metadata. Aliases tracked via IDENTIFIED_AS self-edges.
- **Fact-edges** — AFFILIATED (organizational), ASSERTED (claims/commitments), TRANSITIONED (state changes). Each carries `fact_type`, `source_at`, `recorded_at`, `stale`, `confidence`, `valid_until`.

### Extraction

Consumer subscribed to `records WHERE indexed = FALSE AND classification = 'relevant'`. For each record:

1. Build content from `records.content` column
2. Compose the extraction prompt — agent system prompt + universal rules + entity types + source guidance
3. Run `ExtractorAgent` with read-only graph tools (`find_entity`, `search_entities`, `check_alias`, `get_entity_context`, `save_extraction`). The agent looks up candidates in the graph and decides match-or-new inline — there is no separate resolution pass.
4. Validate the extraction output and commit entities + fact-edges to Neo4j
5. Embed content in Qdrant
6. Mark indexed, enqueue for curator

## Data Access

<p align="center"><img src="assets/write-path.svg" alt="Write Path — Records to Graph" width="640"></p>

`context_query.py` is the single read layer. Both the retriever and MCP server call through it. Extraction and the curator own all writes.

## MCP Server

Read-only query surface via FastMCP over HTTP/SSE. 10 tools: 5 primitive + 5 convenience. API key auth. Starts as daemon thread in `psc run`/`psc dev` (monolith paths) or standalone via `psc mcp start` (decomposed).

## Interfaces

### Monolith (local-dev)

- **`psc run`** — full system + session REPL
- **`psc dev`** — full system + Discord bot (thread-per-session)
- **`psc run --poll` / `psc dev --poll`** — also start expert ingesters

### Decomposed services

- **`psc discord start`** — Discord frontend + bus agents only
- **`psc extraction start`** / **`psc curation start`** / **`psc triage start`** — queue workers
- **`psc mcp start`** — MCP query endpoint
- **`psc expert start-ingestion <name>`** — per-expert live-poll ingester

### Other

- **`psc expert ingest`** — standalone file-based ingestion (one-shot or interactive)
- **`psc chat`** — direct agent chat without the session bus

## See also

- [Getting Started](getting-started.md) — installation, credentials, first run
- [Building an Expert](expert_guide.md) — step-by-step guide to creating a new expert
- [Context Query](context_query.md) — read-only data access layer reference
- [Data Model](data-model.md) — entities, facts, graph schema
- [Usage](usage.md) — full command reference
