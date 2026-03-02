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
pearscaff --version                # print version
pearscaff run                      # worker + experts + session REPL
pearscaff discord                  # worker + experts + Discord bot
pearscaff chat                     # direct chat (no session bus)
pearscaff expert gmail --login     # Gmail login
pearscaff expert gmail             # standalone Gmail expert
```

Also available as `ps --version`, `ps run`, `ps discord`, etc.

## Architecture

```
REPL / Discord (human)
    ↓ SQLite messages
Worker Agent (reasoning, routing)
    ↓ SQLite messages
Expert Agents (Gmail via headless browser)
```

Sessions track conversations. Worker delegates to experts via explicit `send_message` tool calls. Experts reply via a `reply` tool. No auto-replies — agents decide when and to whom to communicate, preventing infinite message loops. All communication is async via SQLite polling. A unified log at `logs/session.log` records every action across all agents.

Emails read by the Gmail expert are persisted to a System of Record (`records` + `emails` tables) with deduplication. The worker can look up stored emails by record ID.

## REPL

Non-blocking prompt with message attribution and live activity indicator:

```
[ses_001] you > read my latest emails
[ses_001] worker working... (2s)
[ses_001] worker > Looking into your emails...
[ses_001] gmail_expert working... (5s)
[ses_001] worker > You have 3 unread emails: ...
[ses_001] you >
```

Commands: `/sessions`, `/switch <id>`, `/new`, `/history [id]`

## Docs

- [Getting Started](docs/getting-started.md)
- [Usage](docs/usage.md)
- [Architecture](docs/architecture.md)
