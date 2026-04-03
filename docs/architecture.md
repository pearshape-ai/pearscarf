# Architecture

## System Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Interfaces                            │
│       Discord / Terminal REPL / MCP Server (HTTP/SSE)    │
└────────────┬──────────────────────────┬─────────────────┘
             │ Postgres messages         │ context_query.py
┌────────────▼──────────────────────────┐│
│            Worker Agent                ││
│   (reasoning, routing, triage)         ││
└──┬──────┬──────┬──────┬───────────────┘│
   │      │      │      │               │
┌──▼──┐┌──▼──┐┌──▼───┐┌─▼────┐  ┌──────▼──────┐
│Gmail││Linear││Ingest││Retrvr│  │ MCP Server  │
│Exprt││Exprt ││Exprt ││      │  │ (10 tools)  │
└──┬──┘└──┬──┘└──┬───┘└──┬───┘  └──────┬──────┘
   │      │      │       │             │
   │writes│writes│writes │reads        │reads
   │      │      │       │             │
┌──▼──────▼──────▼───────▼─────────────▼──────┐
│                  Storage                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Postgres │ │ Neo4j    │ │ Qdrant       │ │
│  │ records  │ │ entities │ │ vectors      │ │
│  │ emails   │ │ fact-    │ │              │ │
│  │ issues   │ │ edges    │ │              │ │
│  │ sessions │ │          │ │              │ │
│  │ mcp_keys │ │          │ │              │ │
│  └──────────┘ └──────────┘ └──────────────┘ │
└──────────────────────────────────────────────┘
        ↑ writes              ↑ writes
┌───────┴──────┐     ┌───────┴──────┐
│   Indexer    │────→│   Curator    │
│ (extraction) │queue│ (dedup,      │
│              │     │  expiry,     │
│              │     │  confidence) │
└──────────────┘     └──────────────┘
```

## Email Pipeline

```
New email arrives
       │
       ▼
┌──────────────┐
│ Gmail Expert │──── stores raw record + email ────┐
└──────┬───────┘                                    │
       │ sends full data to worker                  │
       ▼                                            ▼
┌──────────────┐                           ┌────────────────┐
│   Worker     │                           │ System of      │
│   (triage)   │                           │ Record (Postgres)│
└──────┬───────┘                           └────────────────┘
       │                                            ▲
       ├── known entity? → auto: relevant           │
       ├── obvious noise? → auto: noise             │
       ├── uncertain? → ask human in Discord/REPL   │
       │                                            │
       ▼                                            │
  classification stored on record ──────────────────┘
       │
       │ (if relevant)
       ▼
┌──────────────┐
│   Indexer    │
│  (background)│
└──────┬───────┘
       │
       ├── LLM extraction → entities, edges, facts
       ├── embed content → Qdrant
       └── mark as indexed
```

## Retriever Query Flow

```
"What do I know about Acme Corp?"
       │
       ▼
┌──────────────┐
│  Retriever   │
└──────┬───────┘
       │
       ├── Step 1: Entity match?
       │   └── Yes: "Acme Corp" found in Neo4j graph
       │
       ├── Step 2: Facts lookup
       │   └── total_spend_q3: $13k, payment_terms: net 30
       │
       ├── Step 3: Graph traversal (2-3 hops)
       │   ├── Michael Chen (person) ── works_at ──→ Acme Corp
       │   ├── email_71 (Q3 invoice) ── mentions ──→ Acme Corp
       │   └── email_42 (Partnership) ── mentions ──→ Acme Corp
       │
       ├── Step 4: Vector search (additional context)
       │   └── email_88 (scaling discussion) ── similarity: 0.82
       │
       ▼
┌──────────────────────────────────────────┐
│ Context Package                          │
│  facts: 2 attributes                    │
│  related_records: 3 (2 graph, 1 vector) │
│  entities: 1 person                     │
│  reasoning: "Found entity, 2 facts..."  │
└──────────────────────────────────────────┘
       │
       ▼
  Worker formats and responds to human
```

## Overview

```
pearscarf/
├── agents/
│   ├── base.py           # BaseAgent — agentic loop on raw Anthropic SDK
│   ├── worker.py          # WorkerAgent — context-aware, routes to experts
│   ├── expert.py          # ExpertAgent — domain-specialized, knowledge-collecting
│   └── runner.py          # AgentRunner — polling loop that feeds bus messages to agents
├── experts/
│   ├── __init__.py        # Expert registry
│   ├── gmail.py           # Gmail expert — OAuth API + headless browser fallback
│   ├── linear.py          # Linear expert — GraphQL API, issue CRUD
│   ├── ingest.py          # Ingest expert — file-based data entry (seed + JSON records)
│   └── retriever.py       # Retriever expert — context queries via context_query.py
├── prompts/               # System prompts as standalone markdown files
│   ├── __init__.py        # load(name) — prompt loader
│   ├── worker.md          # Worker agent system prompt
│   ├── gmail_browser.md   # Gmail expert browser transport prompt
│   ├── gmail_mcp.md       # Gmail expert MCP/API transport prompt
│   ├── linear.md          # Linear expert system prompt
│   ├── retriever.md       # Retriever expert system prompt
│   ├── ingest.md          # Ingest expert system prompt
│   ├── extraction.md      # Indexer LLM extraction template
│   ├── ingest_extraction.md # Seed file extraction template
│   ├── entity_resolution.md # Entity resolution LLM judge prompt
│   ├── curator_affiliated.md # Curator AFFILIATED dedup judge
│   └── curator_asserted.md  # Curator ASSERTED dedup judge
├── tools/
│   ├── __init__.py        # BaseTool + ToolRegistry with auto-discovery
│   ├── math.py            # Safe math expression evaluator
│   └── web_search.py      # DuckDuckGo web search
├── context_query.py       # Read-only data access layer — single query surface for retriever + MCP
├── mcp_server.py          # MCP server — FastMCP over HTTP/SSE, exposes 10 tools
├── curator.py             # Curator — background worker for graph quality (dedup, expiry, confidence)
├── curator_judge.py       # LLM judge for semantic equivalence of fact-edges
├── indexer.py             # Indexer — background LLM extraction into knowledge graph
├── graph.py               # Knowledge graph CRUD — entities, fact-edges, traversal
├── db.py                  # Postgres schema + queries (sessions, messages, records, graph)
├── bus.py                 # MessageBus — send/receive/poll over Postgres
├── store.py               # System of Record — structured record/email/issue storage + curator queue
├── vectorstore.py         # Qdrant vector storage — semantic search via sentence-transformers
├── scoring.py             # Eval scoring — entity/fact matching, F1, NRR, ERA, temporal accuracy
├── eval_runner.py         # Eval pipeline — ingest, index, query graph, score
├── eval_report.py         # Eval terminal report formatter + JSON results writer
├── extract_test.py        # Extraction prompt testing utility (no writes)
├── neo4j_client.py        # Neo4j connection manager
├── linear_client.py       # Linear GraphQL API client
├── tracing.py             # LangSmith tracing utilities
├── log.py                 # Shared session logger — unified timeline
├── status.py              # In-memory agent activity registry
├── config.py              # Environment-based configuration
├── terminal.py            # Raw terminal I/O for non-blocking REPL
├── repl.py                # Non-blocking session-aware REPL
├── cli.py                 # Click CLI — run, discord, eval, query, mcp, curator, queue, erase-all
├── cli_memory.py          # Memory inspection CLI commands (psc memory)
└── discord_bot.py         # Discord bot with thread-per-session
```

## Agent Communication

```
Terminal REPL / Discord (human interface)
    ↓ messages via Postgres
Worker Agent (context, reasoning, task routing)
    ↓ messages via Postgres
Expert Agents (headless browser UI operators)
```

All agent-to-agent communication goes through Postgres. There is no direct function calling between agents. Each agent runs in its own thread, polling the database for unread messages.

### Explicit Communication Model

Agents communicate **only through explicit tool calls** — the runner never auto-replies. This prevents infinite ping-pong loops between agents.

- **Worker** uses the `send_message` tool to send messages to humans or experts
- **Experts** use the `reply` tool to send results back to whoever requested work
- If an agent has nothing meaningful to send, it simply doesn't call a send tool, and no message goes out
- The runner's job is: receive message → run the agent → done. All outbound routing is the agent's decision.

## Sessions

Every conversation is a **session** (`ses_001`, `ses_002`, ...). Messages are tagged with a session ID. Sessions can be:
- **Human-initiated**: human types in REPL or Discord, creates a session
- **Expert-initiated**: expert detects an event (e.g. urgent email), creates a session and notifies the worker

Sessions are never closed. They persist and can be resumed at any time.

## Message Flow

### Human → Worker → Expert → Worker → Human

1. Human sends message → `messages(from=human, to=worker, session=ses_001)`
2. Worker picks it up (1s polling), reasons, delegates → `messages(from=worker, to=gmail_expert, session=ses_001)`
3. Expert picks it up, operates browser, responds → `messages(from=gmail_expert, to=worker, session=ses_001)`
4. Worker picks it up, formats for human → `messages(from=worker, to=human, session=ses_001)`
5. REPL/Discord displays the response

### Expert-Initiated Event

1. Expert creates new session, sends to worker
2. Worker decides if human needs to know, responds to human
3. REPL prints notification / Discord creates a new thread

## Database Schema

```sql
-- Communication
sessions(id, initiated_by, summary, created_at)
messages(id, session_id, from_agent, to_agent, content, reasoning, data, read, created_at)
discord_threads(session_id, thread_id, channel_id)

-- System of Record
records(id, type, source, created_at, raw, indexed, classification, classification_reason,
        human_context, resolution_pending, resolution_status)
emails(record_id, message_id, sender, recipient, subject, body, received_at)
issues(record_id, linear_id, identifier, title, description, status, priority, assignee,
       project, labels, comments, url, linear_created_at, linear_updated_at)
issue_changes(record_id, issue_record_id, linear_history_id, field, from_value, to_value,
              changed_by, changed_at)

-- Operations
curator_queue(record_id, queued_at, claimed_at)
mcp_keys(id, name, key_hash, created_at, last_used_at, revoked)
```

Postgres with connection pooling (psycopg_pool) for concurrent reads/writes across threads.

## System of Record

Persistent structured storage for all domain data. Each expert owns writing to its tables; the worker reads.

- **`records`** — Base table shared across all data types. Every record has an `id` (e.g. `email_001`), `type`, and `source` agent. The `indexed` flag tracks whether the Indexer has processed it. The `classification` field (`relevant`/`noise`/NULL) tracks triage status.
- **`emails`** — Gmail-specific table. Deduplication via `message_id` UNIQUE constraint.
- **`store.py`** — CRUD module: `save_email()`, `get_email()`, `list_emails()`, `classify_record()`, `get_pending_records()`.

### Ownership
- **Gmail expert writes**: after reading an email via browser, calls `save_email` tool to persist it.
- **Worker triages**: classifies records as relevant/noise via `classify_record` tool. Checks sender against knowledge graph via `search_entities` tool. Asks human when uncertain.
- **Worker reads**: can look up stored emails via `lookup_email` tool for context.

### Email Triage

When the worker receives an email from the gmail expert, it classifies it before the Indexer processes it:

1. **Known entity** (sender found in graph) → auto-classify as relevant
2. **Obvious noise** (no-reply, promotional, unsubscribe) → auto-classify as noise
3. **Uncertain** → ask the human "Is this relevant and why?"

Human responses are captured as `human_context` on the record. The Indexer appends this context to the extraction prompt, enriching entity extraction. The Indexer only processes records with `classification = 'relevant'`.

**Triage bypass:** Ingest records (`store.save_ingest()`) and issue change records (`store.save_issue_change()`) are auto-classified as `'relevant'` on save — they skip the worker triage step entirely.

## Knowledge Graph

The Indexer processes records into a knowledge graph of entities and fact-edges. All graph data lives in Neo4j. The Retriever queries the graph and vector store via `context_query.py` — the single read-only data access layer shared with the MCP server. Extraction correctness is measured by the metrics defined in [Eval Metrics](eval-metrics.md).

- **Entities** — nodes with labels (Person, Company, Project, Event). Merged on name + email/domain. Aliases tracked via IDENTIFIED_AS self-edges.
- **Fact-edges** — three relationship types: AFFILIATED (organizational), ASSERTED (claims/commitments), TRANSITIONED (state changes). Each carries `fact_type`, `source_at`, `recorded_at`, `stale`, `replaced_by`, `valid_until`. Stale facts are preserved, never deleted.
- **`graph.py`** — CRUD module: `find_entity()`, `create_entity()`, `create_fact_edge()`, `mark_fact_stale()`, `find_entity_candidates()`, `get_entity_context()`.

### Indexer (`indexer.py`)

Background daemon thread that polls `records WHERE indexed = FALSE AND classification = 'relevant' AND resolution_status != 'pending'` every 5 seconds. For each unindexed record:

1. Builds content string from typed table (emails, issues, issue_changes, or raw for ingest records)
2. Loads extraction prompt — `extraction.md` for most records, `ingest_extraction.md` for seed ingests
3. Calls LLM for structured JSON extraction (entities + facts with `edge_label`/`fact_type`)
4. Resolves entities via candidate retrieval: exact name → email/domain → first-name prefix → substring → IDENTIFIED_AS aliases → LLM judge for non-exact matches
5. Writes fact-edges to Neo4j with literal dup check (skip if identical edge already exists from same source)
6. Embeds record content into Qdrant for semantic search
7. Marks record as indexed
8. Enqueues record in `curator_queue` for post-write graph quality processing

Ambiguous entity resolution → record stays `resolution_status = 'pending'`, not marked indexed, skipped on next poll.

Logs to `session.log` as `[indexer]`.

### Vector Storage (`vectorstore.py`)

Qdrant with `all-MiniLM-L6-v2` sentence-transformer embeddings. Connects to a Qdrant Docker server, persists to `data/qdrant/`.

- Single `records` collection — all record types, filterable by metadata (`type`, `source`, `sender`, etc.)
- Lazy-initialized — model and client only load on first use
- `add_record()` — upsert a record's embedding
- `query()` — semantic similarity search with optional metadata filters

## Agent Types

### BaseAgent (`agents/base.py`)

Core agentic loop on the Anthropic Messages API. Callbacks: `on_tool_call`, `on_text`, `on_tool_result`.

### WorkerAgent (`agents/worker.py`)

User-facing agent with a `send_message` tool for all outbound communication. Auto-discovers worker tools (math, web search). Knows about available experts and routes tasks accordingly. Uses `send_message(to="human", ...)` to reply to users and `send_message(to="gmail_expert", ...)` to delegate to experts.

### ExpertAgent (`agents/expert.py`)

Domain-specialized with knowledge accumulation. Built-in `save_knowledge` tool and `reply` tool for sending results back. System prompt includes all previously stored knowledge.

### Retriever (`experts/retriever.py`)

Expert agent that searches the knowledge graph and vector store. The worker delegates context queries to it. Three query modes tried in sequence:

1. **Entity search** — identify known entities referenced in the query
2. **Facts lookup + graph traversal** — get attributes and walk edges up to 3 hops
3. **Vector search** — Qdrant semantic similarity for records not in the graph

Tools: `search_entities`, `facts_lookup`, `graph_traverse`, `vector_search`.

### AgentRunner (`agents/runner.py`)

Polling loop that runs in a background thread. Polls the bus every 1 second, dispatches messages to agents. The runner does **not** auto-reply — agents use their own tools (`send_message`, `reply`) to communicate. Caches one agent instance per session.

### Linear Expert (`experts/linear.py`)

Expert agent for Linear issue management via GraphQL API. Tools: list, get, create, update, comment, search issues. Saves issues to Postgres SOR via `save_issue`. Issue polling via `--poll-linear` flag.

### Ingest Expert (`experts/ingest.py`)

Expert agent for file-based data entry. Two tools: `parse_seed` (typed block markdown) and `parse_record_file` (JSON records). Supports `--seed` and `--record --type` CLI flags for non-interactive use.

### Curator (`curator.py`)

Background worker that processes the `curator_queue` after each record is indexed. Four passes per cycle: AFFILIATED semantic dedup, ASSERTED semantic dedup, expired commitment detection, confidence upgrades. Uses `curator_judge.py` for LLM-based equivalence grouping. See [Curator](curator.md) for full documentation.

## MCP Server

`mcp_server.py` exposes PearScarf's context as a read-only query surface via FastMCP over HTTP/SSE. It is not an agent — it has no reasoning loop, no prompt, and no tools of its own. It translates incoming MCP tool calls into `context_query.py` function calls and returns structured responses.

10 tools registered: 5 primitive (`find_entity`, `get_facts`, `get_connections`, `get_relationship`, `get_conflicts`) and 5 convenience (`get_entity_context`, `get_current_state`, `get_open_commitments`, `get_open_blockers`, `get_recent_activity`).

Named API key auth (`Authorization: Bearer <key>`). Health check at `/health` (no auth). Starts as a background daemon thread in `psc run` and `psc discord`, or standalone via `psc mcp start`.

See [MCP Tools](mcp_tools.md) for the full tool reference.

## Interfaces

### REPL (`pearscarf run`)

Non-blocking session-aware prompt: `[ses_001] you >`. Uses raw terminal I/O so agent responses stream in above the prompt while the user types. Three background threads:

- **Poll thread**: polls bus for messages, prints them above the prompt with `[session] agent >` attribution
- **Status thread**: updates a live activity indicator showing which agent is working and elapsed time (`[ses_001] gmail_expert working... (5s)`)

Commands: `/sessions`, `/switch <id>`, `/new`, `/history [id]`.

### Discord (`pearscarf discord`)

Thread-per-session mapping. New messages create threads. Expert events auto-create threads. All follow-ups within a thread stay in the same session.

### Direct Chat (`pearscarf chat`)

Simple direct mode without the session bus. Useful for quick testing.

### Standalone Expert (`pearscarf expert gmail`)

Direct interaction with the Gmail expert without the bus. Useful for debugging.

## Logging

All agents write to a single shared log file: `data/logs/session.log`. The log is a unified timeline of everything happening across all agents — every tool call, every thought, every message sent and received.

Entry format:
```
[2026-02-27T10:30:01Z] [gmail_expert] [ses_001] [tool] gmail_get_unread({})
[2026-02-27T10:30:02Z] [gmail_expert] [ses_001] [result] gmail_get_unread: Found 3 unread emails
[2026-02-27T10:30:02Z] [gmail_expert] [ses_001] [thinking] 3 unread emails found...
[2026-02-27T10:30:03Z] [worker] [--] [action] polling, none found
```

Entry types: `action`, `message_sent`, `message_received`, `reasoning`, `thinking`, `tool`, `result`, `error`

The log is append-only and thread-safe. Entries without a session use `[--]`.

## Versioning

The version string lives in `pearscarf/__init__.py` as `__version__`. `pyproject.toml` reads it dynamically via hatchling. Available via `pearscarf --version` / `psc --version` and printed in the REPL on startup.

## Data Access Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     WRITE PATH                                │
│                                                              │
│  Records (Gmail, Linear, Ingest)                             │
│       ↓                                                      │
│  Indexer ──writes──→ graph.py / store.py / vectorstore.py    │
│       ↓                                                      │
│  curator_queue (Postgres)                                    │
│       ↓                                                      │
│  Curator ──writes──→ graph.py (stale, confidence)            │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                     READ PATH                                 │
│                                                              │
│  Retriever (internal agents)                                 │
│       ↓                                                      │
│  context_query.py ──reads only──→ graph.py                   │
│       ↑                          store.py                    │
│  MCP Server (external agents)    vectorstore.py              │
└──────────────────────────────────────────────────────────────┘

Storage:
  Neo4j      — entities, fact-edges, Day nodes
  Postgres   — records, emails, issues, curator_queue, mcp_keys
  Qdrant     — vector embeddings
```

The indexer and curator own all writes. `context_query.py` is the only read layer for context-building — it abstracts over Neo4j, Postgres, and Qdrant. The retriever (internal agents) and the MCP server (external agents like Claude, OpenClaw) are two surfaces over the same functions. Internal agents reason about what to call; external agents call directly via MCP tools.

See [Context Query](context_query.md) for the function reference and [MCP Tools](mcp_tools.md) for the external tool surface.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key |
| `MODEL` | `claude-sonnet-4-5-20250929` | Model to use |
| `MAX_TURNS` | `10` | Max agentic loop iterations per message |
| `EXTRACTION_MODEL` | (same as MODEL) | Model for extraction calls |
| `EXTRACTION_MAX_TOKENS` | `2048` | Max output tokens for extraction |
| `DISCORD_BOT_TOKEN` | (required for discord) | Discord bot token |
| `POSTGRES_HOST` | `localhost` | Postgres host |
| `POSTGRES_PORT` | `5432` | Postgres port |
| `POSTGRES_USER` | `pearscarf` | Postgres user |
| `POSTGRES_PASSWORD` | (required) | Postgres password |
| `POSTGRES_DB` | `pearscarf` | Postgres database name |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant server URL |
| `NEO4J_URL` | `bolt://localhost:7687` | Neo4j bolt URL |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | (required) | Neo4j password |
| `GMAIL_CLIENT_ID` | | Google OAuth client ID |
| `GMAIL_CLIENT_SECRET` | | Google OAuth client secret |
| `GMAIL_REFRESH_TOKEN` | | OAuth refresh token |
| `GMAIL_POLL_INTERVAL` | `300` | Email polling interval (seconds) |
| `LINEAR_API_KEY` | | Linear API key |
| `LINEAR_POLL_INTERVAL` | `300` | Linear polling interval (seconds) |
| `LINEAR_TEAM_ID` | | Optional team scope |
| `CURATOR_POLL_INTERVAL` | `30` | Curator poll interval (seconds) |
| `CURATOR_CLAIM_TIMEOUT` | `600` | Curator claim timeout (seconds) |
| `MCP_PORT` | `8090` | MCP server port |
| `MCP_HOST` | `0.0.0.0` | MCP server bind address |
| `TIMEZONE` | `America/Los_Angeles` | Timezone for Day node dates |
| `LANGSMITH_TRACING` | `false` | Enable LangSmith tracing |
| `LANGSMITH_PROJECT` | `pears` | LangSmith project name |
