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

It separates **observed reality** (what shipped, what's true now) from **stated intent** (commitments, plans, goals) — so coworkers don't confuse a promise with a delivery.

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

## Install

One-command install — clones the source, generates a local `.env` with auto-random DB passwords, builds the image, and brings the stack up:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/pearshape-ai/pearscarf/main/install.sh)
```

You'll be asked for an Anthropic API key (for extraction) and an OpenAI API key (for embeddings); the installer auto-generates the DB passwords. Pre-req: Docker daemon running. On success, the MCP URL prints to stdout — paste it into [claude-workforce](https://github.com/pearshape-ai/claude-workforce)'s installer to bring up an AI workforce against this PearScarf.

**To uninstall:** `cd` into the install directory and `bash uninstall.sh` (or run the same curl one-liner pattern with `uninstall.sh`). Destructive — stops containers, wipes data + the install directory entirely.

## Run via Docker (manual)

For finer control — full stack in containers, you author the `.env` yourself:

```bash
# Fill in env/.env at minimum: ANTHROPIC_API_KEY, OPENAI_API_KEY, POSTGRES_PASSWORD, NEO4J_PASSWORD
docker compose up -d
docker compose logs -f pearscarf
```

This brings up Postgres, Qdrant, Neo4j, and the pearscarf app container — auto-installs the shipped experts and exposes the MCP server on port 8090.

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

## Local testing

Two pearscarf stacks run side by side: the dev stack (`docker compose up`) and an isolated test stack on alt ports for repeatable integration tests.

```bash
# one-time: copy the example config
cp env/.test.env.example env/.test.env

# bring up the isolated test stack — postgres / neo4j / qdrant on alt ports,
# under docker compose project name `pearscarf-test`
scripts/test-stack.sh up

# run integration tests against it
uv run pytest --integration

# wipe state + restart for a clean run
scripts/test-stack.sh reset

# tear it down (removes volumes + bind-mount data)
scripts/test-stack.sh down
```

Integration tests live under `tests/integration/` and are marked `@pytest.mark.integration` — a bare `pytest` run skips them. CI continues to run unit tests only (`pytest tests/unit/`).

### Benchmarks against the test stack

`scripts/benchmark.sh` runs an ER eval against the test stack and lands the report (and optionally per-record LLM traces) under `data/test/benchmark-debug/`.

```bash
# requires a real ANTHROPIC_API_KEY in env/.test.env
scripts/benchmark.sh /path/to/eval/dataset                 # one shot
scripts/benchmark.sh /path/to/eval/dataset --debug         # plus LLM prompts/responses
scripts/benchmark.sh /path/to/eval/dataset --no-reset      # run against current stack state
BENCHMARK_DEBUG_DIR=/tmp/bench scripts/benchmark.sh …      # override artifact location
```

Each run captures stdout/stderr to `<BENCHMARK_DEBUG_DIR>/<timestamp>.log`. In debug mode, `psc eval --debug-dir <BENCHMARK_DEBUG_DIR>` writes a sibling `<dataset>_v<ver>_<timestamp>/` containing every LLM prompt and response.

## Docs

- [Getting Started](docs/getting-started.md) — installation, credentials, first run
- [Examples & Usage](docs/examples-usage.md) — three patterns: agents pushing records, polling external systems, adding your own source
- [Architecture](docs/architecture.md) — system design, expert contract, startup flow, prompt composition
- [Building an Expert](docs/expert_guide.md) — step-by-step guide to creating a new expert
- [Deployment Vocabulary](docs/deployment-vocab.md) — declare deployment-specific entity types and fact_types via `vocab.yaml`
- [Usage](docs/usage.md) — full command reference
- [Data Model](docs/data-model.md) — entities, fact types, full schema, bi-temporal model
- [Query Surface](docs/query-surface.md) — MCP tools reference
- [MCP Clients](docs/mcp-clients.md) — connect Claude Code, Claude Desktop, or a custom client
- [Eval Metrics](docs/eval-metrics.md) — extraction precision, recall, entity resolution accuracy
- [Changelog](CHANGELOG.md)

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the current direction and milestones.

## License

Released under the [MIT License](LICENSE).

## Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). First-time contributors sign a one-click CLA via [cla-assistant.io](https://cla-assistant.io/).

---

Open source · Framework-agnostic · Built on Neo4j, Postgres, Qdrant
