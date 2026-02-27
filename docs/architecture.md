# Architecture

## Overview

```
pearscaff/
├── agent.py          # Agentic loop on raw Anthropic SDK
├── cli.py            # Click CLI — chat REPL + discord bot launcher
├── config.py         # Environment-based configuration
├── discord_bot.py    # Discord bot client
└── tools/
    ├── __init__.py   # BaseTool + ToolRegistry with auto-discovery
    ├── math.py       # Safe math expression evaluator
    └── web_search.py # DuckDuckGo web search
```

## Agentic Loop

The core loop in `agent.py` is built directly on the Anthropic Messages API with no framework:

1. Append user message to conversation history
2. Call `client.messages.create()` with tools and full message history
3. If `stop_reason == "end_turn"` — return the text response
4. If `stop_reason == "tool_use"` — execute each tool, append results, go to step 2
5. Safety: loop exits after `MAX_TURNS` iterations

The Agent class holds per-session conversation history in memory. Each Agent instance is a separate conversation.

## Tool System

Tools are defined as subclasses of `BaseTool`:

- `name` — identifier registered with the Anthropic API
- `description` — what the LLM sees
- `input_schema` — JSON Schema for parameters
- `execute(**kwargs) -> str` — runs the tool, returns text

The `ToolRegistry` auto-discovers tools at startup by scanning the `pearscaff/tools/` package for `BaseTool` subclasses using `pkgutil.iter_modules`. To add a new tool, drop a file in `tools/` with a `BaseTool` subclass — no manual registration needed.

## Interfaces

### CLI (`pearscaff chat` / `ps chat`)

Interactive terminal REPL. One Agent instance per session. Tool calls are printed to stdout via the `on_tool_call` callback.

### Discord (`pearscaff discord` / `ps discord`)

Discord bot that responds to @mentions and DMs. Maintains a separate Agent per channel (per-channel conversation history). The sync Anthropic client runs in an executor thread to avoid blocking the async Discord event loop.

## Configuration

All config is via environment variables (loaded from `.env` by python-dotenv):

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key |
| `MODEL` | `claude-sonnet-4-5-20250929` | Model to use |
| `MAX_TURNS` | `10` | Max agentic loop iterations per message |
| `DISCORD_BOT_TOKEN` | (required for discord) | Discord bot token |
