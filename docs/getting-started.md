# Getting Started

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- An Anthropic API key
- Docker (for Postgres, Neo4j, Qdrant)

## Installation

```bash
git clone <repo-url>
cd pearscarf
uv sync
source .venv/bin/activate
```

## Running via Docker (operator path)

For running pearscarf without a local Python setup, the full stack — Postgres, Qdrant, Neo4j, and pearscarf itself — is in `docker-compose.yml`:

```bash
# Fill in env/.env (see Configuration below)
docker compose up -d
docker compose logs -f pearscarf
```

The pearscarf container boots `psc discord --poll` by default. Its entrypoint waits for Postgres, installs any experts under `experts/` that aren't already registered, and then starts the app. MCP server is exposed on port 8090.

If you prefer local dev (iterating on pearscarf source), skip the pearscarf container and run the DBs only:

```bash
docker compose up -d postgres qdrant neo4j
```

## Docker Services

Postgres, Qdrant, Neo4j, and pgAdmin run as Docker containers:

```bash
docker compose up -d postgres qdrant neo4j pgadmin
```

Data persists under `data/`.

**pgAdmin** at `http://localhost:5050` (login: `admin@pearscarf.dev` / `admin`).
**Neo4j** browser at `http://localhost:7474`.

## Configuration

Core config lives in `env/.env`. Expert credentials in `env/.<name>.env`.

```bash
# Copy the template (or create env/.env manually)
cp .env env/.env
```

Required vars in `env/.env`:
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
POSTGRES_PASSWORD=your-password
NEO4J_PASSWORD=your-neo4j-password
DISCORD_BOT_TOKEN=          # only needed for discord mode
```

See [Architecture — Configuration](architecture.md#configuration) for the full variable reference.

## Install Experts

```bash
psc install ./experts/gmailscarf
psc install ./experts/linearscarf
psc install ./experts/githubscarf
```

Each install validates the package, creates typed tables, and scaffolds a credentials file in `env/`.

## Expert Credentials

### Gmail

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → enable **Gmail API** → create OAuth 2.0 credentials (Desktop app)
3. Add Client ID and Client Secret to `env/.gmailscarf.env`
4. Run the auth flow:
   ```bash
   psc expert auth gmailscarf
   ```
5. Copy the printed refresh token into `env/.gmailscarf.env`

### Linear

1. Go to [Linear Settings → API](https://linear.app/settings/api)
2. Create a personal API key
3. Edit `env/.linearscarf.env`:
   ```
   LINEAR_API_KEY=lin_api_your_key_here
   LINEAR_TEAM_ID=YourTeam    # team name, key, or UUID
   ```

### GitHub

1. Go to [GitHub Settings → Tokens](https://github.com/settings/tokens)
2. Create a personal access token (repo scope)
3. Edit `env/.githubscarf.env`:
   ```
   GITHUB_TOKEN=ghp_your_token_here
   GITHUB_REPO=owner/repo
   ```

## Run

```bash
psc run                # system + REPL
psc run --poll         # also start expert ingesters (background polling)
psc discord            # system + Discord bot
psc discord --poll     # Discord + ingesters
```

The pre-startup check validates all expert credentials before booting. Missing vars → clear error message with the file to edit.

## REPL

```
[ses_001] you > Read my latest emails
```

Commands: `/sessions`, `/switch <id>`, `/new`, `/history [id]`

## Discord

- Mention the bot or DM it → new session + thread
- All follow-up in the thread stays in the same session
- Expert events (new email, new issue) auto-create threads

## LangSmith (optional)

Opt-in tracing for LLM calls and tool executions. Add to `env/.env`:

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_your_key_here
LANGSMITH_PROJECT=pears
```

## Next steps

- [Architecture](architecture.md) — system design, expert contract, prompt composition
- [Building an Expert](expert_guide.md) — step-by-step guide to creating a new expert
- [Data Model](data-model.md) — entities, facts, graph schema
- [Usage](usage.md) — full command reference
