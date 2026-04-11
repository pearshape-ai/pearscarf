from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pearscarf.storage import graph
from pearscarf.agents.base import BaseAgent
from pearscarf.expert_context import ExpertContext
from pearscarf.knowledge import load as load_prompt
from pearscarf.tools import BaseTool, ToolRegistry


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


class ClassifyRecordTool(BaseTool):
    """Worker uses this to classify a record as relevant or noise."""

    name = "classify_record"
    description = (
        "Classify a record as 'relevant' or 'noise'. "
        "Use after triaging an email. Include reasoning and any human context."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "record_id": {
                "type": "string",
                "description": "The record ID to classify, e.g. 'email_3f2a1b4c'",
            },
            "classification": {
                "type": "string",
                "enum": ["relevant", "noise"],
                "description": "Classification: 'relevant' or 'noise'",
            },
            "reason": {
                "type": "string",
                "description": "Why this classification was chosen",
            },
            "human_context": {
                "type": "string",
                "description": "Additional context from human response, if any",
            },
        },
        "required": ["record_id", "classification", "reason"],
    }

    def execute(self, **kwargs: Any) -> str:
        from pearscarf.storage import store

        ok = store.classify_record(
            record_id=kwargs["record_id"],
            classification=kwargs["classification"],
            reason=kwargs["reason"],
            human_context=kwargs.get("human_context", ""),
        )
        if not ok:
            return f"Failed to classify {kwargs['record_id']} — record not found."
        return f"Record {kwargs['record_id']} classified as {kwargs['classification']}."


class SearchEntitiesTool(BaseTool):
    """Worker uses this to search the knowledge graph for known entities."""

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


def create_worker_agent(
    ctx: ExpertContext,
    session_id: str,
    on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
    on_text: Callable[[str], None] | None = None,
    on_tool_result: Callable[[str, str], None] | None = None,
) -> BaseAgent:
    """Create a WorkerAgent configured for a specific session."""
    registry = ToolRegistry()
    registry.discover()
    send_tool = SendMessageTool(ctx)
    send_tool._session_id = session_id
    registry.register(send_tool)
    registry.register(ClassifyRecordTool())
    registry.register(SearchEntitiesTool())

    agent = BaseAgent(
        tool_registry=registry,
        system_prompt=load_prompt("worker"),
        agent_name="worker",
        on_tool_call=on_tool_call,
        on_text=on_text,
        on_tool_result=on_tool_result,
    )
    agent._send_tool = send_tool
    return agent
