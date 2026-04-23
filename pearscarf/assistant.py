"""Assistant — Consumer that handles human and expert messages on the bus.

Subscribes to `messages WHERE to_agent='assistant'`. Per session, spawns
(or reuses) an `AssistantAgent` and lets it reason + delegate to experts
via the `send_message` tool.

This is the front-of-house for humans — the component they talk to in
Discord / the REPL. It is not domain-specific; domain-specific bots are
the generic `ExpertBot` instances (one per enabled expert).

The session-caching + history-rebuild machinery lives in
`SessionConsumer`; this module just configures tools + prompt.
"""

from __future__ import annotations

from typing import Any

from pearscarf.agents.base import BaseAgent
from pearscarf.expert_context import ExpertContext
from pearscarf.knowledge import load as load_prompt
from pearscarf.session_consumer import SessionConsumer
from pearscarf.storage import graph
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


class SearchEntitiesTool(BaseTool):
    """Assistant uses this to search the knowledge graph for known entities."""

    name = "search_entities"
    description = (
        "Search the knowledge graph for entities by name, email, or domain. "
        "Use this to check if an email sender is a known person or company."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Name, email address, or domain to search for",
            },
            "entity_type": {
                "type": "string",
                "description": "Optional filter: 'person' or 'company'",
            },
        },
        "required": ["query"],
    }

    def execute(self, **kwargs: Any) -> str:
        query = kwargs["query"]
        entity_type = kwargs.get("entity_type")
        results = graph.search_entities(query, entity_type=entity_type, limit=5)
        if not results:
            return "No entities found."
        lines = []
        for e in results:
            meta = e.get("metadata", {})
            meta_str = ", ".join(f"{k}={v}" for k, v in meta.items()) if meta else ""
            line = f"- {e['name']} ({e['type']}, id={e['id']})"
            if meta_str:
                line += f"  [{meta_str}]"
            lines.append(line)
        return "\n".join(lines)


class AssistantAgent(BaseAgent):
    """LLM agent spawned per session by `Assistant` to reason + delegate."""

    def __init__(
        self,
        tool_registry,
        system_prompt: str = "",
        on_tool_call=None,
        on_text=None,
        on_tool_result=None,
    ) -> None:
        super().__init__(
            tool_registry=tool_registry,
            system_prompt=system_prompt,
            agent_name="assistant",
            on_tool_call=on_tool_call,
            on_text=on_text,
            on_tool_result=on_tool_result,
        )


class Assistant(SessionConsumer):
    """Consumer that handles bus messages addressed to the assistant."""

    name = "assistant"

    def _build_agent(self, session_id: str) -> AssistantAgent:
        registry = ToolRegistry()
        send_tool = SendMessageTool(self._ctx)
        send_tool._session_id = session_id
        registry.register(send_tool)
        registry.register(SearchEntitiesTool())

        on_tool_call, on_text, on_tool_result = self._session_logging_callbacks(session_id)
        agent = AssistantAgent(
            tool_registry=registry,
            system_prompt=load_prompt("assistant"),
            on_tool_call=on_tool_call,
            on_text=on_text,
            on_tool_result=on_tool_result,
        )
        agent._send_tool = send_tool
        return agent
