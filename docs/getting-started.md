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

Copy the example env file and fill in your keys:

```bash
cp .env.example .env
```

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
DISCORD_BOT_TOKEN=          # only needed for discord mode
```

## Usage

### CLI Chat (Worker Agent)

```bash
pearscaff chat
# or
ps chat
```

Interactive REPL with the worker agent. It can use tools (math, web search) automatically. Type `exit` or Ctrl+C to quit.

### Discord Bot (Worker Agent)

```bash
pearscaff discord
# or
ps discord
```

Requires `DISCORD_BOT_TOKEN` in `.env`. Responds to @mentions and DMs.

#### Discord Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to Bot settings, create a bot
4. Enable **Message Content Intent** under Privileged Gateway Intents
5. Copy the bot token to your `.env`
6. Go to OAuth2 > URL Generator, select `bot` scope with `Send Messages` and `Read Message History` permissions
7. Use the generated URL to invite the bot to your server

### Gmail Expert

First, log into Gmail (opens a visible browser):

```bash
pearscaff expert gmail --login
```

Log in to your Google account in the browser that opens, then press Enter in the terminal. Your session is saved for future use.

Then run the expert:

```bash
pearscaff expert gmail
# or
ps expert gmail
```

Ask the expert to read your emails, summarize your inbox, or mark emails as read. It operates Gmail through a headless browser and prints results to the terminal.
