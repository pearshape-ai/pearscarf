# Architecture

## Overview

```
pearscaff/
├── agents/
│   ├── base.py           # BaseAgent — agentic loop on raw Anthropic SDK
│   ├── worker.py          # WorkerAgent — context-aware, routes to experts
│   ├── expert.py          # ExpertAgent — domain-specialized, knowledge-collecting
│   └── runner.py          # AgentRunner — polling loop that feeds bus messages to agents
├── experts/
│   ├── __init__.py        # Expert registry
│   ├── gmail.py           # Gmail expert — headless browser automation
│   └── retriever.py       # Retriever expert — knowledge graph + vector search
├── knowledge/
│   └── __init__.py        # KnowledgeStore — file-based markdown storage
├── tools/
│   ├── __init__.py        # BaseTool + ToolRegistry with auto-discovery
│   ├── math.py            # Safe math expression evaluator
│   └── web_search.py      # DuckDuckGo web search
├── db.py                  # SQLite schema + queries (sessions, messages, records, graph)
├── bus.py                 # MessageBus — send/receive/poll over SQLite
├── store.py               # System of Record — structured email/record storage
├── graph.py               # Knowledge graph CRUD — entities, edges, facts
├── indexer.py             # Indexer — background LLM extraction into knowledge graph
├── vectorstore.py         # ChromaDB vector storage — embeddings for semantic search
├── log.py                 # Shared session logger — unified timeline
├── status.py              # In-memory agent activity registry
├── terminal.py            # Raw terminal I/O for non-blocking REPL
├── repl.py                # Non-blocking session-aware REPL
├── cli.py                 # Click CLI — run, discord, chat, expert commands
├── config.py              # Environment-based configuration
└── discord_bot.py         # Discord bot with thread-per-session
```

## Agent Communication

```
Terminal REPL / Discord (human interface)
    ↓ messages via SQLite
Worker Agent (context, reasoning, task routing)
    ↓ messages via SQLite
Expert Agents (headless browser UI operators)
```

All agent-to-agent communication goes through SQLite. There is no direct function calling between agents. Each agent runs in its own thread, polling the database for unread messages.

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
records(id, type, source, created_at, raw, indexed, classification, classification_reason, human_context)
emails(record_id, message_id, sender, recipient, subject, body, received_at)

-- Knowledge Graph
entity_types(id, name, description, extract_fields, added_at)
entities(id, type, name, metadata, created_at)
edges(id, from_entity, to_entity, relationship, source_record, created_at)
facts(id, entity_id, attribute, value, source_record, updated_at)
```

SQLite with WAL mode for concurrent reads/writes across threads.

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

## Knowledge Graph

The Indexer processes records into a knowledge graph of entities, relationships, and facts.

- **`entity_types`** — Registry of extractable types (person, company). Seeded on first run. Drives the LLM extraction prompt.
- **`entities`** — Graph nodes. Sequential IDs per type (`person_001`, `company_001`). Metadata stored as JSON.
- **`edges`** — Graph relationships between entities (e.g. `person_001 --works_at--> company_001`). Linked to source record.
- **`facts`** — Living state attributes on entities (e.g. person's email, role). Upserted — same entity+attribute updates rather than duplicates.
- **`graph.py`** — CRUD module: `find_entity()`, `create_entity()`, `create_edge()`, `upsert_fact()`.

### Indexer (`indexer.py`)

Background daemon thread that polls `records WHERE indexed = 0` every 5 seconds. For each unindexed record:

1. Reads full content from typed table (e.g. emails)
2. Builds extraction prompt from `entity_types` registry
3. Calls LLM for structured JSON extraction
4. Resolves entities against existing graph (exact name + metadata match)
5. Creates edges and upserts facts
6. Embeds record content into ChromaDB for semantic search
7. Marks record as indexed

Logs to `session.log` as `[indexer]`.

### Vector Storage (`vectorstore.py`)

ChromaDB with `all-MiniLM-L6-v2` sentence-transformer embeddings. Runs embedded (no server), persists to `chroma_data/`.

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
3. **Vector search** — ChromaDB semantic similarity for records not in the graph

Tools: `search_entities`, `facts_lookup`, `graph_traverse`, `vector_search`.

### AgentRunner (`agents/runner.py`)

Polling loop that runs in a background thread. Polls the bus every 1 second, dispatches messages to agents. The runner does **not** auto-reply — agents use their own tools (`send_message`, `reply`) to communicate. Caches one agent instance per session.

## Interfaces

### REPL (`pearscaff run`)

Non-blocking session-aware prompt: `[ses_001] you >`. Uses raw terminal I/O so agent responses stream in above the prompt while the user types. Three background threads:

- **Poll thread**: polls bus for messages, prints them above the prompt with `[session] agent >` attribution
- **Status thread**: updates a live activity indicator showing which agent is working and elapsed time (`[ses_001] gmail_expert working... (5s)`)

Commands: `/sessions`, `/switch <id>`, `/new`, `/history [id]`.

### Discord (`pearscaff discord`)

Thread-per-session mapping. New messages create threads. Expert events auto-create threads. All follow-ups within a thread stay in the same session.

### Direct Chat (`pearscaff chat`)

Simple direct mode without the session bus. Useful for quick testing.

### Standalone Expert (`pearscaff expert gmail`)

Direct interaction with the Gmail expert without the bus. Useful for debugging.

## Logging

All agents write to a single shared log file: `logs/session.log`. The log is a unified timeline of everything happening across all agents — every tool call, every thought, every message sent and received.

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

The version string lives in `pearscaff/__init__.py` as `__version__`. `pyproject.toml` reads it dynamically via hatchling. Available via `pearscaff --version` / `ps --version` and printed in the REPL on startup.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key |
| `MODEL` | `claude-sonnet-4-5-20250929` | Model to use |
| `MAX_TURNS` | `10` | Max agentic loop iterations per message |
| `DISCORD_BOT_TOKEN` | (required for discord) | Discord bot token |
| `DB_PATH` | `pearscaff.db` | SQLite database file path |
