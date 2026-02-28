# Architecture

## Overview

```
pearscaff/
├── agents/
│   ├── base.py           # BaseAgent — agentic loop on raw Anthropic SDK
│   ├── worker.py          # WorkerAgent — user-facing agent (chat, discord)
│   └── expert.py          # ExpertAgent — domain-specialized, knowledge-collecting
├── experts/
│   ├── __init__.py        # Expert registry
│   └── gmail.py           # Gmail expert — headless browser automation
├── knowledge/
│   ├── __init__.py        # KnowledgeStore — file-based markdown storage
│   └── gmail/             # Gmail expert's accumulated knowledge
├── tools/
│   ├── __init__.py        # BaseTool + ToolRegistry with auto-discovery
│   ├── math.py            # Safe math expression evaluator
│   └── web_search.py      # DuckDuckGo web search
├── cli.py                 # Click CLI — chat, discord, expert commands
├── config.py              # Environment-based configuration
└── discord_bot.py         # Discord bot client
```

## Agent Types

### BaseAgent (`agents/base.py`)

The core agentic loop built directly on the Anthropic Messages API:

1. Append user message to conversation history
2. Call `client.messages.create()` with tools, system prompt, and message history
3. If `stop_reason == "end_turn"` — return the text response
4. If `stop_reason == "tool_use"` — execute each tool, append results, go to step 2
5. Safety: loop exits after `MAX_TURNS` iterations

Supports callbacks: `on_tool_call`, `on_text`, `on_tool_result` for verbose output.

### WorkerAgent (`agents/worker.py`)

The user-facing agent. Uses auto-discovered tools from `tools/` (math, web search). Accessed via `pearscaff chat` and `pearscaff discord`.

### ExpertAgent (`agents/expert.py`)

Domain-specialized agent that accumulates knowledge over time. Each expert has:
- A domain-specific system prompt
- A `KnowledgeStore` that persists learned information as markdown files
- A built-in `save_knowledge` tool to record operational insights
- Knowledge is loaded into the system prompt on startup, so the expert gets better with use

## Tool System

Tools are `BaseTool` subclasses with `name`, `description`, `input_schema`, and `execute()`. The `ToolRegistry` handles registration and auto-discovery.

Worker tools (math, web search) are auto-discovered from `tools/`. Expert tools are registered directly per-expert.

## Gmail Expert

Uses **Playwright** to control a headless Chromium browser to operate Gmail's web UI.

**Browser tools:** navigate, click, type, get_text, get_html, screenshot, wait — give the agent full browser control.

**Gmail tools:** get_unread, read_latest, mark_as_read — encode known-good Gmail workflows.

**Auth:** Uses Playwright's persistent browser context (`storage_state.json`). First login via `--login` flag opens a visible browser for the user to log in manually. Session is saved and reused.

**Knowledge:** The expert stores what it learns about navigating Gmail (selectors, timing, patterns) in `knowledge/gmail/`. This knowledge is loaded into the system prompt on future runs.

**Output:** Emails are printed to the terminal. Reasoning, tool calls, and results are also printed for visibility.

## Interfaces

### CLI Chat (`pearscaff chat`)

Interactive terminal REPL with the WorkerAgent.

### Discord (`pearscaff discord`)

Discord bot using the WorkerAgent. Per-channel conversation history. Responds to @mentions and DMs.

### Expert (`pearscaff expert gmail`)

Interactive terminal REPL with the Gmail ExpertAgent. Verbose output shows tool calls, reasoning, and results as the expert operates.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key |
| `MODEL` | `claude-sonnet-4-5-20250929` | Model to use |
| `MAX_TURNS` | `10` | Max agentic loop iterations per message |
| `DISCORD_BOT_TOKEN` | (required for discord) | Discord bot token |
