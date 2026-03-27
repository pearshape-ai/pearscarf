<p align="center">
  <img width="271" height="294" alt="PearScarf logo" src="https://github.com/user-attachments/assets/ecaf3cc6-a8a1-4af9-a5ee-545b7e9d38ef" />
</p>

<h1 align="center">PearScarf</h1>

<p align="center">
  Context engine for team of agents.
</p>

<p align="center">
  <a href="docs/roadmap.md">Roadmap</a> · <a href="docs/architecture.md">Architecture</a> · <a href="docs/eval-metrics.md">Eval Metrics</a> · <a href="docs/getting-started.md">Getting Started</a> · <a href="CHANGELOG.md">Changelog</a>
</p>

---

PearScarf is a context engine for team of agents. It watches your data sources (Gmail, Linear, Notion, etc), extracts what matters, and maintains a living knowledge graph — so your operational agents have access and use the context that matters instead of rebuilding it from scratch. 200 tokens instead of 10,000.

**Fully promptable.** Entity types, fact categories, extraction rules — all plain-language prompts you can edit. PearScarf fits your world, not the other way around.

## How it works

```
Data Sources (Gmail, Linear, ...)
    ↓ polling
PearScarf observes → extracts entities & facts → maintains temporal graph
    ↓
Any agent queries PearScarf for context
    ↓
Structured answer with provenance, confidence, and history
```

## What's inside

- **Worker agent** — reasoning, routing, human-in-the-loop triage
- **Expert agents** — Gmail (OAuth API), Linear (GraphQL API), more to come
- **Extraction pipeline** — LLM-powered entity and fact extraction, driven by editable prompts
- **Temporal knowledge graph** — Neo4j with entities, Day nodes, and categorized fact-edges carrying provenance and timestamps
- **Vector search** — Qdrant for semantic similarity when the query is fuzzy
- **System of Record** — Postgres for raw data, sessions, and agent communication
- **Observability** — every LLM call and graph write traced via LangSmith
- **Discord & REPL interfaces** — interact with the system through chat

## Quick Start

```bash
uv sync
source .venv/bin/activate
playwright install chromium
docker compose up -d           # Postgres, Qdrant, Neo4j
cp .env.example .env          # add ANTHROPIC_API_KEY + POSTGRES_PASSWORD

psc gmail --auth               # Gmail OAuth setup
psc run                        # start the full system
psc run --poll-email           # start with automatic email polling
psc run --poll-linear          # start with automatic Linear issue polling
```

## Commands

```bash
psc --version                  # print version
psc run                        # worker + experts + session REPL
psc run --poll-email           # full system + email polling
psc run --poll-linear          # full system + Linear polling
psc discord                    # worker + experts + Discord bot
psc discord --poll-email       # Discord + email polling
psc chat                       # direct chat (no session bus)
psc gmail --auth               # Gmail OAuth setup for API access
psc expert gmail               # standalone Gmail expert
psc expert linear              # standalone Linear expert
psc expert ingest              # standalone ingest expert (interactive)
psc expert ingest --seed <file>              # ingest seed file
psc expert ingest --record <file> --type email  # ingest JSON records
psc extract-test <record_id>   # test extraction on a specific record
psc eval --dataset <path>     # run extraction eval against a dataset
psc eval --dataset <path> -v  # verbose: print record content + expected/extracted per record
psc erase-all                  # wipe all system state (with confirmation)
psc memory list                # list stored memories
psc memory search "query"      # search memories
psc memory entity "name"       # look up entity + connections
psc memory graph               # graph stats overview
psc memory record <id>         # memories from a specific record
```

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

## Trust by design

Every fact traces to its source. Nothing is silently overwritten. The system asks when it's uncertain. Humans can correct it when it's wrong. See [Trust & Human Control](docs/roadmap.md#trust--human-control) in the roadmap.

## Docs

- [Getting Started](docs/getting-started.md)
- [Usage](docs/usage.md)
- [Architecture](docs/architecture.md)
- [Eval Metrics](docs/eval-metrics.md)
- [Roadmap](docs/roadmap.md)
- [Changelog](CHANGELOG.md)