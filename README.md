# pearscarf

<p align="center">
  <img width="271" height="294" alt="PearScarf logo" src="https://github.com/user-attachments/assets/ecaf3cc6-a8a1-4af9-a5ee-545b7e9d38ef" />
</p>
Operational infrastructure that grows itself.

Multi-agent system with async communication over Postgres. A worker agent handles reasoning and routing, expert agents access domain services through APIs or headless browsers.

## Quick Start

```bash
uv sync
source .venv/bin/activate
playwright install chromium
docker compose up -d           # start Postgres, Qdrant, Neo4j
cp .env.example .env          # add ANTHROPIC_API_KEY + POSTGRES_PASSWORD

pearscarf gmail --auth             # Gmail OAuth setup (or: expert gmail --login for browser)
pearscarf run                      # start the full system
pearscarf run --poll-email         # start with automatic email polling
pearscarf run --poll-linear        # start with automatic Linear issue polling
```

## Commands

```bash
pearscarf --version                # print version
pearscarf run                      # worker + experts + session REPL
pearscarf run --poll-email         # full system + automatic email polling
pearscarf discord                  # worker + experts + Discord bot
pearscarf discord --poll-email     # Discord + email polling
pearscarf chat                     # direct chat (no session bus)
pearscarf gmail --auth             # Gmail OAuth setup for API access
pearscarf expert gmail --login     # Gmail browser login (legacy)
pearscarf expert gmail             # standalone Gmail expert
pearscarf expert linear            # standalone Linear expert
pearscarf memory list              # list stored memories
pearscarf memory search "query"    # search memories
pearscarf memory entity "name"     # look up entity + connections
pearscarf memory graph             # graph stats overview
pearscarf memory record <id>       # memories from a specific record
```

Also available as `ps --version`, `ps run`, `ps discord`, etc.

## Architecture

```
REPL / Discord (human)
    ↓ Postgres messages
Worker Agent (reasoning, routing, triage)
    ↓ Postgres messages
Expert Agents (Gmail API/browser, Linear API, Retriever)
    ↓
Indexer (background) → Knowledge Graph (Neo4j) + Vector Store (Qdrant)
```

Sessions track conversations. Worker delegates to experts via explicit `send_message` tool calls. Experts reply via a `reply` tool. No auto-replies — agents decide when and to whom to communicate, preventing infinite message loops. All communication is async via Postgres polling. A unified log at `data/logs/session.log` records every action across all agents.

Emails read by the Gmail expert are persisted to a System of Record with deduplication. The worker triages each email — auto-classifying known senders and obvious noise, asking the human when uncertain. A background Indexer extracts entities and facts into a knowledge graph (Neo4j) and embeds records in Qdrant for semantic search. The Retriever expert searches the knowledge graph and vector store when the worker needs context.

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
