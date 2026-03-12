# pearscaff

Operational infrastructure that grows itself.

Multi-agent system with async communication over SQLite. A worker agent handles reasoning and routing, expert agents access domain services through APIs or headless browsers.

## Quick Start

```bash
uv sync
source .venv/bin/activate
playwright install chromium
cp .env.example .env          # add ANTHROPIC_API_KEY

pearscaff gmail --auth             # Gmail OAuth setup (or: expert gmail --login for browser)
pearscaff run                      # start the full system
pearscaff run --poll-email         # start with automatic email polling
```

## Commands

```bash
pearscaff --version                # print version
pearscaff run                      # worker + experts + session REPL
pearscaff run --poll-email         # full system + automatic email polling
pearscaff discord                  # worker + experts + Discord bot
pearscaff discord --poll-email     # Discord + email polling
pearscaff chat                     # direct chat (no session bus)
pearscaff gmail --auth             # Gmail OAuth setup for API access
pearscaff expert gmail --login     # Gmail browser login (legacy)
pearscaff expert gmail             # standalone Gmail expert
pearscaff memory list              # list stored memories
pearscaff memory search "query"    # search memories
pearscaff memory entity "name"     # look up entity + connections
pearscaff memory graph             # graph stats overview
pearscaff memory record <id>       # memories from a specific record
```

Also available as `ps --version`, `ps run`, `ps discord`, etc.

## Architecture

```
REPL / Discord (human)
    ↓ SQLite messages
Worker Agent (reasoning, routing, triage)
    ↓ SQLite messages
Expert Agents (Gmail API/browser, Retriever)
    ↓
Indexer (background) → Memory Backend (Mem0+Neo4j or SQLite+ChromaDB)
```

Sessions track conversations. Worker delegates to experts via explicit `send_message` tool calls. Experts reply via a `reply` tool. No auto-replies — agents decide when and to whom to communicate, preventing infinite message loops. All communication is async via SQLite polling. A unified log at `logs/session.log` records every action across all agents.

Emails read by the Gmail expert are persisted to a System of Record with deduplication. The worker triages each email — auto-classifying known senders and obvious noise, asking the human when uncertain. A background Indexer processes relevant records through a pluggable memory backend — either Mem0 (with Neo4j graph + vector) or the original SQLite+ChromaDB pipeline. The Retriever expert searches the memory layer when the worker needs context.

## REPL

Non-blocking prompt with message attribution and live activity indicator:

```
[ses_001] you > read my latest emails
[ses_001] worker working... (2s)
[ses_001] worker > Looking into your emails...
[ses_001] gmail_expert working... (5s)
[ses_001] worker > You have 3 unread emails: ...
[ses_001] you >
```

Commands: `/sessions`, `/switch <id>`, `/new`, `/history [id]`, `/memory`

## Docs

- [Getting Started](docs/getting-started.md)
- [Usage](docs/usage.md)
- [Architecture](docs/architecture.md)
- [Changelog](CHANGELOG.md)
