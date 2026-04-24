"""Assistant — Consumer that handles human and expert messages on the bus.

Subscribes to `messages WHERE to_agent='assistant'`. Per session, spawns
(or reuses) an `AssistantAgent` and lets it reason + delegate to experts
via the `send_message` tool, or query the knowledge graph directly via
the graph query tools folded in from the retired Retriever.

This is the front-of-house for humans — the component they talk to in
Discord / the REPL.
"""

from __future__ import annotations

from typing import Any

from pearscarf.agents.base import BaseAgent
from pearscarf.expert_context import ExpertContext
from pearscarf.graph_query_tools import (
    DayLookupTool,
    FactsLookupTool,
    GraphTraverseTool,
    SearchEntitiesTool,
    VectorSearchTool,
)
from pearscarf.knowledge import load as load_prompt
from pearscarf.session_consumer import SessionConsumer
from pearscarf.tools import BaseTool, ToolRegistry


class SendMessageTool(BaseTool):
    """Assistant uses this to send messages to any agent or to the human."""

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
                "description": "Recipient: 'human', or an expert name like 'gmailscarf'",
            },
            "content": {
                "type": "string",
                "description": "The message content to send",
            },
        },
        "required": ["to", "content"],
    }

    def __init__(self, ctx: ExpertContext) -> None:
        self._ctx = ctx
        self._session_id: str | None = None

    def execute(self, **kwargs: Any) -> str:
        to = kwargs["to"]
        content = kwargs["content"]
        if not self._session_id:
            return "Error: no active session set."
        self._ctx.bus.send(
            session_id=self._session_id,
            to_agent=to,
            content=content,
        )
        self._ctx.log.write(
            self._ctx.expert_name,
            "message_sent",
            f"to={to}: {content[:200]}",
        )
        return f"Message sent to {to}."


class AssistantAgent(BaseAgent):
    """LLM agent spawned per session by `Assistant` to reason + delegate."""

    # Attached by `Assistant._build_agent` so downstream tool-handling code
    # can reach the session-scoped `SendMessageTool` without threading it
    # through BaseAgent's callback signature.
    _send_tool: SendMessageTool | None = None

    def __init__(
        self,
        tool_registry,
        system_prompt: str = "",
        on_tool_call=None,
        on_text=None,
        on_tool_result=None,
        max_turns: int | None = None,
    ) -> None:
        super().__init__(
            tool_registry=tool_registry,
            system_prompt=system_prompt,
            agent_name="assistant",
            on_tool_call=on_tool_call,
            on_text=on_text,
            on_tool_result=on_tool_result,
            max_turns=max_turns,
        )


class Assistant(SessionConsumer):
    """Consumer that handles bus messages addressed to the assistant."""

    name = "assistant"
    max_turns = 15

    def _build_agent(self, session_id: str) -> AssistantAgent:
        registry = ToolRegistry()
        send_tool = SendMessageTool(self._ctx)
        send_tool._session_id = session_id
        registry.register(send_tool)
        # Graph query tools — folded in from the retired Retriever
        registry.register(SearchEntitiesTool())
        registry.register(FactsLookupTool())
        registry.register(GraphTraverseTool())
        registry.register(DayLookupTool())
        registry.register(VectorSearchTool())

        on_tool_call, on_text, on_tool_result = self._session_logging_callbacks(session_id)
        agent = AssistantAgent(
            tool_registry=registry,
            system_prompt=load_prompt("assistant"),
            on_tool_call=on_tool_call,
            on_text=on_text,
            on_tool_result=on_tool_result,
            max_turns=self.max_turns,
        )
        agent._send_tool = send_tool
        return agent
