# Getting Started

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- An Anthropic API key

## Installation

```bash
git clone <repo-url>
cd pearscarf
uv sync
source .venv/bin/activate
playwright install chromium
```

## Configuration

```bash
cp .env.example .env
```

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
DISCORD_BOT_TOKEN=          # only needed for discord mode
```

## Gmail Setup

Two options for connecting Gmail:

### Option A: Gmail OAuth (recommended)

API-based access via OAuth2. Enables email polling.

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or use an existing one)
3. Enable the **Gmail API** (APIs & Services → Library → search "Gmail API")
4. Create OAuth 2.0 credentials (APIs & Services → Credentials → Create Credentials → OAuth client ID → Desktop app)
5. Copy Client ID and Client Secret to `.env`:
   ```
   GMAIL_CLIENT_ID=your-client-id.apps.googleusercontent.com
   GMAIL_CLIENT_SECRET=your-client-secret
   ```
6. Run the auth flow:
   ```bash
   pearscarf gmail --auth
   ```
7. Complete the consent screen in your browser. The refresh token is printed — add it to `.env`:
   ```
   GMAIL_REFRESH_TOKEN=your-refresh-token
   ```

### Option B: Headless Browser (legacy)

Uses a Playwright browser to navigate Gmail's web UI:

```bash
pearscarf expert gmail --login
```

Log in, complete 2FA, then press Enter in the terminal. Session saved for reuse.

If both OAuth credentials and a browser session exist, OAuth (API) is used by default.

## Docker Services

Postgres (application data), Qdrant (vector search), pgAdmin (database UI), and Neo4j (knowledge graph) run as Docker containers. A `docker-compose.yml` is provided:

```bash
# Set POSTGRES_PASSWORD in .env first
docker compose up -d
```

This starts all services with data persisted under `data/`.

Add Postgres credentials to `.env`:
```
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=pearscarf
POSTGRES_PASSWORD=your-password
POSTGRES_DB=pearscarf
```

**pgAdmin** is available at `http://localhost:5050`. Default login: `admin@pearscarf.dev` / `admin` (override via `PGADMIN_EMAIL` and `PGADMIN_PASSWORD` in `.env`). To connect to the database, add a server with host `postgres`, port `5432`, and your Postgres credentials.

**Neo4j** is required for the extraction pipeline — entities, relationships, and facts are stored here. Set `NEO4J_PASSWORD` in `.env` (default auth: `neo4j/<password>`). Browser available at `http://localhost:7474`.

## Linear Setup (optional — issue management)

1. Go to [Linear Settings → API](https://linear.app/settings/api)
2. Create a personal API key
3. Add to `.env`:
   ```
   LINEAR_API_KEY=lin_api_your_key_here
   LINEAR_TEAM_ID=               # optional — team name, key, or UUID to scope polling
   ```

Test with:
```bash
pearscarf expert linear
```

Enable automatic issue syncing with `--poll-linear`:
```bash
pearscarf run --poll-linear
pearscarf discord --poll-linear
```

## LangSmith Setup (optional — observability)

Opt-in tracing for LLM calls, tool executions, and cost tracking.

1. Sign up at [smith.langchain.com](https://smith.langchain.com)
2. Create an API key
3. Add to `.env`:
   ```
   LANGSMITH_TRACING=true
   LANGSMITH_API_KEY=lsv2_your_key_here
   LANGSMITH_PROJECT=pears
   ```

When not configured, the system runs with zero tracing overhead.

## Usage

### Full System (recommended)

```bash
pearscarf run
```

Starts worker agent + Gmail expert + session-aware REPL. All communication goes through Postgres.

```
[ses_001] > Read my latest emails
[ses_001] > /sessions
[ses_001] > /switch ses_002
[ses_002] > /history
```

### Discord Mode

```bash
pearscarf discord
```

Same system but with Discord as the frontend. Each session maps to a Discord thread.

### Direct Chat (no bus)

```bash
pearscarf chat
```

Simple direct mode without sessions or agent routing. Good for quick testing.

### Standalone Gmail Expert

```bash
pearscarf expert gmail
```

Direct interaction with the Gmail expert. Useful for debugging browser tools.

## Discord Bot Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application → Bot → enable **Message Content Intent**
3. Copy bot token to `.env`
4. OAuth2 → URL Generator → `bot` scope → `Send Messages`, `Read Message History`, `Create Public Threads`, `Send Messages in Threads`
5. Invite bot to your server
