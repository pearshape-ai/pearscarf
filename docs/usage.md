# Usage

## Commands

| Command | Description |
|---|---|
| `pearscaff run` | Full system: worker + experts + session REPL |
| `pearscaff run --poll-email` | Full system with automatic email polling |
| `pearscaff discord` | Full system with Discord frontend |
| `pearscaff discord --poll-email` | Discord mode with automatic email polling |
| `pearscaff chat` | Direct chat (no session bus) |
| `pearscaff gmail --auth` | Run Gmail OAuth flow for API-based access |
| `pearscaff expert gmail` | Standalone Gmail expert |
| `pearscaff expert gmail --login` | Log into Gmail via browser (legacy) |
| `pearscaff expert gmail --auth` | Gmail OAuth setup (same as `gmail --auth`) |

All commands also available via `ps`.

## Session REPL (`pearscaff run`)

The REPL shows the active session in the prompt:

```
[ses_001] > Read my latest emails
```

### REPL Commands

| Command | Description |
|---|---|
| `/sessions` | List all sessions (id, initiated_by, summary) |
| `/switch <id>` | Switch to a different session |
| `/new` | Create a new session |
| `/history` | Print messages in current session |
| `/history <id>` | Print messages in a specific session |

### Message Flow

When you type a message:
1. It's sent to the **worker agent** via SQLite
2. Worker reasons about it — may delegate to an **expert agent**
3. Expert processes (e.g. reads Gmail via API or headless browser)
4. Result flows back: expert → worker → you

### Notifications

When an expert creates a new session (e.g. urgent email detected):
```
--- NEW MESSAGE ses_003: worker — Urgent email from investor@acme.com ---
```

Use `/switch ses_003` to interact with that session.

## Discord (`pearscaff discord`)

- New message in a channel → creates a new session + Discord thread
- All follow-up in the thread stays in the same session
- Expert-initiated events auto-create threads
- Sessions persist — resume by posting in the thread

## Worker Agent Tools

### math
Safe expression evaluator: `+`, `-`, `*`, `/`, `**`, `sqrt`, `log`, `sin`, `cos`, `pi`, `e`

### web_search
DuckDuckGo web search

### delegate_to_expert
Routes tasks to expert agents (e.g. `gmail_expert` for email operations)

## Gmail Expert Tools

### API transport (OAuth)

**Gmail:** `gmail_get_unread`, `gmail_read_email`, `gmail_search`, `gmail_mark_as_read`

### Browser transport (legacy)

**Browser:** `browser_navigate`, `browser_click`, `browser_type`, `browser_get_text`, `browser_get_html`, `browser_screenshot`, `browser_wait`

**Gmail:** `gmail_get_unread`, `gmail_read_latest`, `gmail_mark_as_read`

**Knowledge:** `save_knowledge` — stores operational knowledge for future sessions

## Email Polling

Enable automatic email checking with `--poll-email`:

```bash
pearscaff run --poll-email
pearscaff discord --poll-email
```

Requires Gmail OAuth credentials. Checks every `GMAIL_POLL_INTERVAL` seconds (default: 300).

Each new email:
1. Gets saved to the System of Record
2. Creates a new session
3. Triggers worker triage (auto-classify or ask human)
4. Shows up as a notification in Discord/REPL

## Adding Custom Worker Tools

Drop a `BaseTool` subclass in `pearscaff/tools/`:

```python
from typing import Any
from pearscaff.tools import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "Description for the LLM"
    input_schema = {
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "..."}
        },
        "required": ["param"],
    }

    def execute(self, **kwargs: Any) -> str:
        return f"Result for {kwargs['param']}"
```

Auto-discovered at startup.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key |
| `MODEL` | `claude-sonnet-4-5-20250929` | Model identifier |
| `MAX_TURNS` | `10` | Max tool-call loop iterations |
| `DISCORD_BOT_TOKEN` | (required for discord) | Discord bot token |
| `DB_PATH` | `pearscaff.db` | SQLite database path |
| `GMAIL_CLIENT_ID` | | Google OAuth client ID |
| `GMAIL_CLIENT_SECRET` | | Google OAuth client secret |
| `GMAIL_REFRESH_TOKEN` | | OAuth refresh token (from `gmail --auth`) |
| `GMAIL_POLL_INTERVAL` | `300` | Email polling interval in seconds |
