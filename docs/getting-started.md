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

Log into Gmail (opens a visible browser):

```bash
pearscaff expert gmail --login
```

Log in, complete 2FA, then press Enter in the terminal. Session saved for reuse.

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
