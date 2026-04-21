<p align="center">
  <img width="271" height="294" alt="PearScarf logo" src="https://github.com/user-attachments/assets/ecaf3cc6-a8a1-4af9-a5ee-545b7e9d38ef" />
</p>

<h1 align="center">PearScarf</h1>

<p align="center">
  Self-improving context engine for teams of agents.
</p>

<p align="center">
  <a href="docs/getting-started.md">Getting Started</a> · <a href="docs/architecture.md">Architecture</a> · <a href="docs/expert_guide.md">Building an Expert</a> · <a href="docs/usage.md">Usage</a> · <a href="CHANGELOG.md">Changelog</a>
</p>

---

PearScarf is a self-improving, reality-aligned context engine for teams of agents, built on a bi-temporal knowledge graph.

It watches your data sources — Gmail, Linear, GitHub, and more — extracts what matters, and makes it queryable by any agent in your system. One structured call. Sourced, dated, current context. No raw record processing on every run.

## Why current approaches fall short

Teams of agents deal with heterogeneous data — emails, issues, PRs, calendar, CRM — all connected in your head but siloed for your agents. Vector storage-based RAG loses those connections and when things happened. Stuffing raw records into context grows with every new source, and still leaves every agent rebuilding the same connections on every run.

## One call. Everything your agent needs to know.

PearScarf sits between your data sources and your agents. It observes records as they arrive, extracts structured facts with full provenance, and maintains those facts over time — nothing silently overwritten, history always preserved. When an agent needs context, it asks PearScarf. One call returns everything known about an entity: current state, recent activity, open commitments, blockers.

PearScarf is itself an agent — built and run as one. Its captures and maintaines the state of the world so your other agents don't have to.

> **For MCP-compatible frameworks**
>
> Connect once via MCP. Every agent in your system gets access to the same shared, up-to-date context — without writing any retrieval logic.

## Expert plugin architecture

PearScarf uses a plugin system called **experts**. Each expert is a self-contained package that owns two-way access to a data source:

- **gmailscarf** — Gmail via OAuth API
- **linearscarf** — Linear via GraphQL API
- **githubscarf** — GitHub via REST API

Experts are installed, versioned, and managed independently. Building a new expert requires no changes to PearScarf core — just a manifest, a connect module, and knowledge files.

```
experts/gmailscarf/
├── manifest.yaml          # declares record types, schemas, entry points
├── gmail_connect.py       # API client + tools + record ingestion
├── gmail_ingest.py        # background polling loop
├── schemas/email.json     # JSON Schema for the email record type
└── knowledge/
    ├── agent.md           # LLM agent prompt
    └── extraction.md      # source-specific extraction guidance
```

## Run via Docker

Fastest path from zero to running — full stack in containers:

```bash
# Fill in env/.env at minimum: ANTHROPIC_API_KEY, POSTGRES_PASSWORD, NEO4J_PASSWORD, DISCORD_BOT_TOKEN
docker compose up -d
docker compose logs -f pearscarf
```

This brings up Postgres, Qdrant, Neo4j, and the pearscarf app container running `psc discord --poll` — auto-installs the shipped experts and exposes the MCP server on port 8090.

## Quick start (local dev)

For iterating on pearscarf itself — run the app on your host, DBs in Docker:

```bash
uv sync
source .venv/bin/activate
docker compose up -d postgres qdrant neo4j   # skip the pearscarf container

# Install experts
psc install ./experts/gmailscarf
psc install ./experts/linearscarf
psc install ./experts/githubscarf

# Configure credentials
psc expert auth gmailscarf     # Gmail OAuth setup
# Edit env/.linearscarf.env    # add LINEAR_API_KEY
# Edit env/.githubscarf.env    # add GITHUB_TOKEN + GITHUB_REPO

# Optional: tell the extraction agent about your world
# cp docs/onboarding.example.md env/onboarding.md && $EDITOR env/onboarding.md
# Then set ONBOARDING_PROMPT_PATH=env/onboarding.md in env/.env

# Run
psc run                        # start system + REPL
psc run --poll                 # also start expert ingesters
psc discord --poll             # Discord frontend + ingesters
```

## Commands

| Command | Description |
|---|---|
| `psc run` | Worker + experts + session REPL |
| `psc run --poll` | Full system + expert ingesters |
| `psc discord` | Worker + experts + Discord bot |
| `psc discord --poll` | Discord + expert ingesters |
| `psc install <path>` | Install an expert package |
| `psc update <name>` | Update an installed expert |
| `psc expert list` | List installed experts |
| `psc expert inspect <name>` | Show expert details |
| `psc expert auth <name>` | Run an expert's auth flow (e.g. `gmailscarf`) |
| `psc expert start-ingestion <name>` | Run an expert's ingester standalone |
| `psc expert ingest --seed <file>` | Ingest a seed file |
| `psc expert ingest --record <file> --type <type>` | Ingest JSON records |
| `psc eval --dataset <path>` | Run eval against a dataset |
| `psc indexer start` | Run the indexer standalone |
| `psc triage start` | Run the triage agent standalone |
| `psc mcp start` | Run MCP server standalone |
| `psc erase-all` | Wipe all system state |

## Docs

- [Getting Started](docs/getting-started.md) — installation, credentials, first run
- [Architecture](docs/architecture.md) — system design, expert contract, startup flow, prompt composition
- [Building an Expert](docs/expert_guide.md) — step-by-step guide to creating a new expert
- [Usage](docs/usage.md) — full command reference
- [Data Model](docs/data-model.md) — entities, fact types, full schema, bi-temporal model
- [Query Surface](docs/query-surface.md) — MCP tools reference
- [Eval Metrics](docs/eval-metrics.md) — extraction precision, recall, entity resolution accuracy
- [Changelog](CHANGELOG.md)

## License

Released under the [MIT License](LICENSE).

## Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). First-time contributors sign a one-click CLA via [cla-assistant.io](https://cla-assistant.io/).

---

Open source · Framework-agnostic · Built on Neo4j, Postgres, Qdrant
