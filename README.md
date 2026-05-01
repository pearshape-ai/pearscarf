<p align="center">
  <img width="271" height="294" alt="PearScarf logo" src="https://github.com/user-attachments/assets/ecaf3cc6-a8a1-4af9-a5ee-545b7e9d38ef" />
</p>

<h1 align="center">PearScarf</h1>

<p align="center">
  Shared operational brain for teams of AI coworkers.
</p>

<p align="center">
  <a href="docs/getting-started.md">Getting Started</a> · <a href="docs/architecture.md">Architecture</a> · <a href="docs/expert_guide.md">Building an Expert</a> · <a href="docs/usage.md">Usage</a> · <a href="CHANGELOG.md">Changelog</a>
</p>

---

PearScarf is the shared operational brain for your AI coworkers — a knowledge graph of the work your team has actually done, sourced from the systems where the work lives, not from what someone said about it in a thread. Every coworker reads from the same view; none of them rebuild context on every run.

It separates **observed reality** (what shipped, what's true now) from **stated intention** (commitments, plans, goals) — so coworkers don't confuse a promise with a delivery.

## Your operation isn't in the chat

Most agent-memory tools learn from conversations — a noisy log of one assistant's exchanges with one user. Your operation lives elsewhere: in Linear issues, Gmail threads, GitHub PRs, calendar events, CRM updates, Spreadsheets. PearScarf reads from those systems directly and keeps the connections between them in a graph. Vector retrieval over raw records loses those connections; hand-maintained markdown systems go stale.

## One call. Everything your coworker needs to know.

PearScarf watches your operational systems — Linear, Gmail, GitHub — and extracts structured facts with full provenance. Nothing silently overwritten, history always preserved. When a coworker needs context, it asks PearScarf. One call returns everything known about an entity: current state, recent activity, open commitments, blockers — sourced and dated.

PearScarf is itself multi-agent, self-evolving system with conversational, mcp interfaces. It captures and maintains the state of your operation so your other coworkers don't have to.

> **For MCP-compatible frameworks**
>
> Connect once via MCP. Every coworker in your fleet reads from the same shared brain.

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

This brings up Postgres, Qdrant, Neo4j, and the pearscarf app container running `psc dev --poll` — auto-installs the shipped experts and exposes the MCP server on port 8090.

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
psc dev --poll                 # Local-dev monolith: Discord frontend + all services + ingesters
```

## Commands

| Command | Description |
|---|---|
| `psc run` | Assistant + experts + session REPL |
| `psc run --poll` | Full system + expert ingesters |
| `psc dev` | Local-dev monolith: Discord + all services in one process |
| `psc dev --poll` | Monolith + expert ingesters |
| `psc discord start` | Discord frontend service (decomposed runtime) |
| `psc install <path>` | Install an expert package |
| `psc update <name>` | Update an installed expert |
| `psc expert list` | List installed experts |
| `psc expert inspect <name>` | Show expert details |
| `psc expert auth <name>` | Run an expert's auth flow (e.g. `gmailscarf`) |
| `psc expert start-ingestion <name>` | Run an expert's ingester standalone |
| `psc expert ingest --seed <file>` | Ingest a seed file |
| `psc expert ingest --record <file> --type <type>` | Ingest JSON records |
| `psc eval --dataset <path>` | Run eval against a dataset |
| `psc extraction start` | Run the extraction consumer standalone |
| `psc triage start` | Run the triage agent standalone |
| `psc mcp start` | Run MCP server standalone |
| `psc erase-all` | Wipe all system state |

## Docs

- [Getting Started](docs/getting-started.md) — installation, credentials, first run
- [Architecture](docs/architecture.md) — system design, expert contract, startup flow, prompt composition
- [Building an Expert](docs/expert_guide.md) — step-by-step guide to creating a new expert
- [Deployment Vocabulary](docs/deployment-vocab.md) — declare deployment-specific entity types and fact_types via `vocab.yaml`
- [Usage](docs/usage.md) — full command reference
- [Data Model](docs/data-model.md) — entities, fact types, full schema, bi-temporal model
- [Query Surface](docs/query-surface.md) — MCP tools reference
- [MCP Clients](docs/mcp-clients.md) — connect Claude Code, Claude Desktop, or a custom client
- [Eval Metrics](docs/eval-metrics.md) — extraction precision, recall, entity resolution accuracy
- [Changelog](CHANGELOG.md)

## License

Released under the [MIT License](LICENSE).

## Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). First-time contributors sign a one-click CLA via [cla-assistant.io](https://cla-assistant.io/).

---

Open source · Framework-agnostic · Built on Neo4j, Postgres, Qdrant
