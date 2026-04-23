"""Assistant — Consumer that handles human and expert messages on the bus.

Subscribes to `messages WHERE to_agent='assistant'`. Per message, loads
the session, spawns (or reuses) an `AssistantAgent` for that session,
rebuilds conversation history from the bus, and lets the agent reason
+ delegate to experts via the `send_message` tool.

This is the front-of-house for humans — the component they talk to in
Discord / the REPL. It is not domain-specific; domain-specific bots are
the expert `*Bot` consumers.
"""

from __future__ import annotations

import json
import traceback
from typing import Any

from pearscarf import log, status
from pearscarf.agents.base import BaseAgent
from pearscarf.bus import MessageBus
from pearscarf.consumer import Consumer
from pearscarf.expert_context import ExpertContext
from pearscarf.knowledge import load as load_prompt
from pearscarf.storage import graph
from pearscarf.tools import BaseTool, ToolRegistry
from pearscarf.tracing import trace_span


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


class Assistant(Consumer):
    """Consumer that handles bus messages addressed to the assistant."""

    name = "assistant"
    default_poll_interval = 1.0

    def __init__(
        self,
        ctx: ExpertContext,
        bus: MessageBus,
        poll_interval: float | None = None,
    ) -> None:
        super().__init__(poll_interval=poll_interval)
        self._ctx = ctx
        self._bus = bus
        self._agents: dict[str, AssistantAgent] = {}
        self._pending: list = []

    def _next(self):
        if self._pending:
            return self._pending.pop(0)
        messages = self._bus.poll(self.name)
        if not messages:
            return None
        self._pending = list(messages)
        return self._pending.pop(0) if self._pending else None

    def _handle(self, msg: dict) -> None:
        session_id = msg["session_id"]
        from_agent = msg["from_agent"]
        content = msg["content"]

        log.write(
            self.name, session_id, "message_received",
            f"from={from_agent}: {content[:200]}",
        )

        agent = self._get_agent(session_id)
        status.set_status(self.name, session_id, "working")
        try:
            with trace_span(
                f"{self.name}.process_message",
                run_type="chain",
                metadata={
                    "agent": self.name,
                    "session_id": session_id,
                    "from_agent": from_agent,
                },
                inputs={"content": content[:500]},
            ) as span:
                # Set session context on send tool
                if hasattr(agent, "_send_tool") and agent._send_tool:
                    agent._send_tool._session_id = session_id

                # Rebuild conversation history for this session
                history = self._bus.get_history(session_id)
                agent._messages.clear()
                for h in history:
                    if h["from_agent"] == self.name:
                        agent._messages.append(
                            {"role": "assistant", "content": h["content"]}
                        )
                    else:
                        agent._messages.append(
                            {"role": "user", "content": h["content"]}
                        )
                # Drop the last user message — agent.run(content) will append it
                if agent._messages and agent._messages[-1]["role"] == "user":
                    agent._messages.pop()

                response = agent.run(content)

                log.write(
                    self.name, session_id, "thinking",
                    f"agent output (not sent): {response[:200]}",
                )
                if span:
                    span.end(outputs={"response": response[:500]})
        finally:
            status.clear_status(self.name, session_id)

    def _get_agent(self, session_id: str) -> AssistantAgent:
        if session_id not in self._agents:
            self._agents[session_id] = self._make_session_agent(session_id)
        return self._agents[session_id]

    def _make_session_agent(self, session_id: str) -> AssistantAgent:
        """Build a per-session AssistantAgent with tools + logging callbacks."""
        registry = ToolRegistry()
        send_tool = SendMessageTool(self._ctx)
        send_tool._session_id = session_id
        registry.register(send_tool)
        registry.register(SearchEntitiesTool())

        def on_tool_call(tool_name: str, args: dict) -> None:
            log.write(self.name, session_id, "tool", f"{tool_name}({json.dumps(args)})")

        def on_text(text: str) -> None:
            log.write(self.name, session_id, "thinking", text)

        def on_tool_result(tool_name: str, result: str) -> None:
            preview = result[:500] if len(result) > 500 else result
            log.write(self.name, session_id, "result", f"{tool_name}: {preview}")

        agent = AssistantAgent(
            tool_registry=registry,
            system_prompt=load_prompt("assistant"),
            on_tool_call=on_tool_call,
            on_text=on_text,
            on_tool_result=on_tool_result,
        )
        agent._send_tool = send_tool
        return agent
