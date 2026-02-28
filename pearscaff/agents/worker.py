from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pearscaff import log
from pearscaff.agents.base import BaseAgent
from pearscaff.bus import MessageBus
from pearscaff.tools import BaseTool, ToolRegistry

WORKER_SYSTEM_PROMPT = """\
You are the worker agent in the pearscaff system. You are the primary interface \
between the human user and expert agents.

Your responsibilities:
- Understand what the human is asking for
- If the request involves email/Gmail operations, delegate to the gmail_expert \
using the send_message tool
- If you can answer directly (general questions, reasoning), do so and send the \
answer to the human using send_message
- When you receive results back from an expert, summarize and present them clearly \
to the human using send_message

Available experts:
- gmail_expert: Operates Gmail through a headless browser. Can read emails, \
list unread messages, mark as read, and perform other Gmail operations.

IMPORTANT: You MUST use the send_message tool to communicate. Your text responses \
are only logged internally — nobody sees them unless you use send_message.

- Use send_message(to="human", ...) to respond to the user.
- Use send_message(to="gmail_expert", ...) to delegate tasks to experts.
- Do NOT send thank-you or farewell messages to experts. When you receive results \
from an expert, process them and send_message to human. That's it.
"""


class SendMessageTool(BaseTool):
    """Worker uses this to send messages to any agent or to the human."""

    name = "send_message"
    description = (
        "Send a message to another agent or to the human user. "
        "You MUST use this tool for all communication — your text output "
        "is only logged internally and nobody sees it unless you use send_message."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient: 'human', or an expert name like 'gmail_expert'",
            },
            "content": {
                "type": "string",
                "description": "The message content to send",
            },
        },
        "required": ["to", "content"],
    }

    def __init__(self, bus: MessageBus) -> None:
        self._bus = bus
        self._session_id: str | None = None

    def execute(self, **kwargs: Any) -> str:
        to = kwargs["to"]
        content = kwargs["content"]
        if not self._session_id:
            return "Error: no active session set."
        self._bus.send(
            session_id=self._session_id,
            from_agent="worker",
            to_agent=to,
            content=content,
            reasoning=f"Worker message to {to}",
        )
        log.write(
            "worker",
            self._session_id,
            "message_sent",
            f"to={to}: {content[:200]}",
        )
        return f"Message sent to {to}."


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
    send_tool = SendMessageTool(bus)
    send_tool._session_id = session_id
    registry.register(send_tool)

    agent = BaseAgent(
        tool_registry=registry,
        system_prompt=WORKER_SYSTEM_PROMPT,
        on_tool_call=on_tool_call,
        on_text=on_text,
        on_tool_result=on_tool_result,
    )
    agent._send_tool = send_tool
    return agent
