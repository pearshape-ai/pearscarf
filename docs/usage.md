# Usage

## Commands

| Command | Description |
|---|---|
| `pearscaff chat` | Interactive chat with the worker agent |
| `pearscaff discord` | Run worker agent as a Discord bot |
| `pearscaff expert gmail` | Run the Gmail expert agent |
| `pearscaff expert gmail --login` | Log into Gmail (first-time setup) |

All commands are also available via `ps` (e.g. `ps chat`, `ps expert gmail`).

## Worker Agent

The worker agent is the general-purpose user-facing agent with tool access.

### Built-in Tools

#### math

Safe mathematical expression evaluator. Supports:
- Arithmetic: `+`, `-`, `*`, `/`, `//`, `**`, `%`
- Functions: `sqrt`, `log`, `log2`, `log10`, `sin`, `cos`, `tan`, `abs`, `round`
- Constants: `pi`, `e`

Example prompt: *"What is sqrt(144) + 15 * 3?"*

#### web_search

Web search via DuckDuckGo API. Returns summaries and related topics.

Example prompt: *"Search for the latest Python release"*

### Adding Custom Worker Tools

Create a new file in `pearscaff/tools/` with a `BaseTool` subclass:

```python
from typing import Any
from pearscaff.tools import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "What the LLM sees when deciding to use this tool"
    input_schema = {
        "type": "object",
        "properties": {
            "param": {
                "type": "string",
                "description": "Description for the LLM",
            }
        },
        "required": ["param"],
    }

    def execute(self, **kwargs: Any) -> str:
        param = kwargs["param"]
        return f"Result for {param}"
```

The tool is auto-discovered at startup — no registration needed.

## Gmail Expert

The Gmail expert operates Gmail through a headless Chromium browser. It can read emails, summarize your inbox, and mark emails as read.

### Setup

Run `pearscaff expert gmail --login` to open a visible browser. Log into your Gmail account and press Enter in the terminal. Your session is saved to `storage_state.json`.

### Usage

```bash
pearscaff expert gmail
```

The expert prints detailed output as it works:
- **[thinking]** — the agent's reasoning
- **[tool]** — tool calls being made (browser actions)
- **[result]** — tool results
- **expert >** — the agent's final response with email contents

### Available Tools

**Browser tools:** `browser_navigate`, `browser_click`, `browser_type`, `browser_get_text`, `browser_get_html`, `browser_screenshot`, `browser_wait`

**Gmail tools:** `gmail_get_unread`, `gmail_read_latest`, `gmail_mark_as_read`

**Knowledge:** `save_knowledge` — the expert stores what it learns about operating Gmail so it gets better over time

### Knowledge System

The Gmail expert accumulates knowledge in `pearscaff/knowledge/gmail/` as markdown files. This includes CSS selectors, navigation patterns, timing info, and workarounds. Knowledge is loaded into the expert's system prompt on startup.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key |
| `MODEL` | `claude-sonnet-4-5-20250929` | Model identifier |
| `MAX_TURNS` | `10` | Max tool-call loop iterations per message |
| `DISCORD_BOT_TOKEN` | (required for discord) | Discord bot token |
