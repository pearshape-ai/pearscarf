from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pearscaff.agents.base import BaseAgent
from pearscaff.bus import MessageBus
from pearscaff.tools import BaseTool, ToolRegistry

WORKER_SYSTEM_PROMPT = """\
You are the worker agent in the pearscaff system. You are the primary interface \
between the human user and expert agents.

Your responsibilities:
- Understand what the human is asking for
- If the request involves email/Gmail operations, delegate to the gmail_expert using the delegate_to_expert tool
- If you can answer directly (general questions, reasoning), do so without delegating
- When you receive results back from an expert, summarize and present them clearly to the human

Available experts:
- gmail_expert: Operates Gmail through a headless browser. Can read emails, \
list unread messages, mark as read, and perform other Gmail operations.

When delegating, be specific about what the expert should do. \
Include your reasoning about why you're delegating.
"""


class DelegateToExpertTool(BaseTool):
    name = "delegate_to_expert"
    description = (
        "Send a task to an expert agent. The expert will process it asynchronously "
        "and send the result back. Use this for domain-specific operations like "
        "reading emails (gmail_expert)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "expert_name": {
                "type": "string",
                "description": "The expert to delegate to, e.g. 'gmail_expert'",
            },
            "task": {
                "type": "string",
                "description": "Clear description of what the expert should do",
            },
        },
        "required": ["expert_name", "task"],
    }

    def __init__(self, bus: MessageBus, session_id: str) -> None:
        self._bus = bus
        self._session_id = session_id

    def execute(self, **kwargs: Any) -> str:
        expert_name = kwargs["expert_name"]
        task = kwargs["task"]
        self._bus.send(
            session_id=self._session_id,
            from_agent="worker",
            to_agent=expert_name,
            content=task,
            reasoning=f"Delegating to {expert_name}: {task[:100]}",
        )
        return f"Task delegated to {expert_name}. The expert will process it and respond."


def create_worker_agent(
    bus: MessageBus,
    session_id: str,
    on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
    on_text: Callable[[str], None] | None = None,
    on_tool_result: Callable[[str, str], None] | None = None,
) -> BaseAgent:
    """Create a WorkerAgent configured for a specific session."""
    registry = ToolRegistry()
    registry.discover()
    registry.register(DelegateToExpertTool(bus, session_id))

    return BaseAgent(
        tool_registry=registry,
        system_prompt=WORKER_SYSTEM_PROMPT,
        on_tool_call=on_tool_call,
        on_text=on_text,
        on_tool_result=on_tool_result,
    )
