# Usage

## Commands

| Command | Description |
|---|---|
| `pearscaff chat` | Interactive terminal chat with the agent |
| `pearscaff discord` | Run as a Discord bot |

Both commands are also available as `ps chat` and `ps discord`.

## Built-in Tools

The agent has access to the following tools:

### math

Safe mathematical expression evaluator. Supports:
- Arithmetic: `+`, `-`, `*`, `/`, `//`, `**`, `%`
- Functions: `sqrt`, `log`, `log2`, `log10`, `sin`, `cos`, `tan`, `abs`, `round`
- Constants: `pi`, `e`

Example prompt: *"What is sqrt(144) + 15 * 3?"*

### web_search

Web search via DuckDuckGo API. Returns summaries and related topics.

Example prompt: *"Search for the latest Python release"*

## Adding Custom Tools

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

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key |
| `MODEL` | `claude-sonnet-4-5-20250929` | Model identifier |
| `MAX_TURNS` | `10` | Max tool-call loop iterations per message |
| `DISCORD_BOT_TOKEN` | (required for discord) | Discord bot token |
