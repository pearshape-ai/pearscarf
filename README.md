# pearscaff

Operational infrastructure that grows itself.

An AI agent with tool access, usable from the terminal or as a Discord bot.

## Quick Start

```bash
uv sync
source .venv/bin/activate
cp .env.example .env   # add your ANTHROPIC_API_KEY
pearscaff chat
```

## Commands

```bash
pearscaff chat      # interactive terminal REPL
pearscaff discord   # run as a Discord bot
```

Also available as `ps chat` and `ps discord`.

## Built-in Tools

- **math** — safe expression evaluator (arithmetic, trig, logarithms)
- **web_search** — DuckDuckGo web search

## Docs

- [Getting Started](docs/getting-started.md)
- [Usage](docs/usage.md)
- [Architecture](docs/architecture.md)
