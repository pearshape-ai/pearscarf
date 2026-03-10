# Getting Started

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- An Anthropic API key

## Installation

```bash
git clone <repo-url>
cd pearscaff
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
   pearscaff gmail --auth
   ```
7. Complete the consent screen in your browser. The refresh token is printed — add it to `.env`:
   ```
   GMAIL_REFRESH_TOKEN=your-refresh-token
   ```

### Option B: Headless Browser (legacy)

Uses a Playwright browser to navigate Gmail's web UI:

```bash
pearscaff expert gmail --login
```

Log in, complete 2FA, then press Enter in the terminal. Session saved for reuse.

If both OAuth credentials and a browser session exist, OAuth (API) is used by default.

## Usage

### Full System (recommended)

```bash
pearscaff run
```

Starts worker agent + Gmail expert + session-aware REPL. All communication goes through SQLite.

```
[ses_001] > Read my latest emails
[ses_001] > /sessions
[ses_001] > /switch ses_002
[ses_002] > /history
```

### Discord Mode

```bash
pearscaff discord
```

Same system but with Discord as the frontend. Each session maps to a Discord thread.

### Direct Chat (no bus)

```bash
pearscaff chat
```

Simple direct mode without sessions or agent routing. Good for quick testing.

### Standalone Gmail Expert

```bash
pearscaff expert gmail
```

Direct interaction with the Gmail expert. Useful for debugging browser tools.

## Discord Bot Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application → Bot → enable **Message Content Intent**
3. Copy bot token to `.env`
4. OAuth2 → URL Generator → `bot` scope → `Send Messages`, `Read Message History`, `Create Public Threads`, `Send Messages in Threads`
5. Invite bot to your server
