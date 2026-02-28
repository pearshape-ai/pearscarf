# pearscaff

Operational infrastructure that grows itself.

Multi-agent system with async communication over SQLite. A worker agent handles reasoning and routing, expert agents operate domain-specific UIs through headless browsers.

## Quick Start

```bash
uv sync
source .venv/bin/activate
playwright install chromium
cp .env.example .env          # add ANTHROPIC_API_KEY

pearscaff expert gmail --login  # first-time Gmail login
pearscaff run                   # start the full system
```

## Commands

```bash
pearscaff run                     # worker + experts + session REPL
pearscaff discord                 # worker + experts + Discord bot
pearscaff chat                    # direct chat (no session bus)
pearscaff expert gmail --login    # Gmail login
pearscaff expert gmail            # standalone Gmail expert
```

Also available as `ps run`, `ps discord`, etc.

## Architecture

```
REPL / Discord (human)
    ↓ SQLite messages
Worker Agent (reasoning, routing)
    ↓ SQLite messages
Expert Agents (Gmail via headless browser)
```

Sessions track conversations. Worker delegates to experts. Experts accumulate operational knowledge. All communication is async via SQLite polling.

## REPL Session Commands

```
[ses_001] > Read my latest emails
[ses_001] > /sessions
[ses_001] > /switch ses_002
[ses_002] > /history
[ses_002] > /new
```

## Docs

- [Getting Started](docs/getting-started.md)
- [Usage](docs/usage.md)
- [Architecture](docs/architecture.md)
