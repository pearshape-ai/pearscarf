# pearscaff

Operational infrastructure that grows itself.

AI agents with tool access — a worker agent for general tasks (terminal + Discord) and expert agents for domain-specific operations.

## Quick Start

```bash
uv sync
source .venv/bin/activate
playwright install chromium
cp .env.example .env   # add your ANTHROPIC_API_KEY
pearscaff chat
```

## Commands

```bash
pearscaff chat                    # worker agent REPL
pearscaff discord                 # worker agent as Discord bot
pearscaff expert gmail --login    # log into Gmail (first time)
pearscaff expert gmail            # Gmail expert REPL
```

Also available as `ps chat`, `ps discord`, `ps expert gmail`.

## Architecture

**Worker Agent** — general-purpose, user-facing. Tools: math, web search. Interfaces: terminal REPL, Discord bot.

**Expert Agents** — domain-specialized, operate via CLI, accumulate knowledge over time.
- **Gmail Expert** — operates Gmail through a headless browser. Reads emails, summarizes inbox, marks as read. Stores navigation knowledge for future sessions.

## Docs

- [Getting Started](docs/getting-started.md)
- [Usage](docs/usage.md)
- [Architecture](docs/architecture.md)
