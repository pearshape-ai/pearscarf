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

### CLI Chat

```bash
pearscaff chat
# or
ps chat
```

Interactive REPL. Type your message, get a response. The agent can use tools (math, web search) automatically. Type `exit` or Ctrl+C to quit.

### Discord Bot

```bash
pearscaff discord
# or
ps discord
```

Requires `DISCORD_BOT_TOKEN` set in `.env`. The bot responds to @mentions in server channels and to DMs. Each channel gets its own conversation history.

#### Discord Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to Bot settings, create a bot
4. Enable **Message Content Intent** under Privileged Gateway Intents
5. Copy the bot token to your `.env`
6. Go to OAuth2 > URL Generator, select `bot` scope with `Send Messages` and `Read Message History` permissions
7. Use the generated URL to invite the bot to your server
