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
│   └── gmail.py           # Gmail expert — headless browser automation
├── knowledge/
│   └── __init__.py        # KnowledgeStore — file-based markdown storage
├── tools/
│   ├── __init__.py        # BaseTool + ToolRegistry with auto-discovery
│   ├── math.py            # Safe math expression evaluator
│   └── web_search.py      # DuckDuckGo web search
├── db.py                  # SQLite schema + queries (sessions, messages)
├── bus.py                 # MessageBus — send/receive/poll over SQLite
├── repl.py                # Session-aware REPL
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
sessions(id, initiated_by, summary, created_at)
messages(id, session_id, from_agent, to_agent, content, reasoning, data, read, created_at)
discord_threads(session_id, thread_id, channel_id)
```

SQLite with WAL mode for concurrent reads/writes across threads.

## Agent Types

### BaseAgent (`agents/base.py`)

Core agentic loop on the Anthropic Messages API. Callbacks: `on_tool_call`, `on_text`, `on_tool_result`.

### WorkerAgent (`agents/worker.py`)

User-facing agent with a `delegate_to_expert` tool. Auto-discovers worker tools (math, web search). Knows about available experts and routes tasks accordingly.

### ExpertAgent (`agents/expert.py`)

Domain-specialized with knowledge accumulation. Built-in `save_knowledge` tool. System prompt includes all previously stored knowledge.

### AgentRunner (`agents/runner.py`)

Polling loop that runs in a background thread. Polls the bus every 1 second, dispatches messages to agents, sends responses back. Caches one agent instance per session.

## Interfaces

### REPL (`pearscaff run`)

Session-aware prompt: `[ses_001] >`. Commands: `/sessions`, `/switch <id>`, `/new`, `/history [id]`. Background thread polls for responses and notifications.

### Discord (`pearscaff discord`)

Thread-per-session mapping. New messages create threads. Expert events auto-create threads. All follow-ups within a thread stay in the same session.

### Direct Chat (`pearscaff chat`)

Simple direct mode without the session bus. Useful for quick testing.

### Standalone Expert (`pearscaff expert gmail`)

Direct interaction with the Gmail expert without the bus. Useful for debugging.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key |
| `MODEL` | `claude-sonnet-4-5-20250929` | Model to use |
| `MAX_TURNS` | `10` | Max agentic loop iterations per message |
| `DISCORD_BOT_TOKEN` | (required for discord) | Discord bot token |
| `DB_PATH` | `pearscaff.db` | SQLite database file path |
