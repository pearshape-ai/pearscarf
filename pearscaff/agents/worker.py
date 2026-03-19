from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pearscaff import graph, log
from pearscaff.agents.base import BaseAgent
from pearscaff.bus import MessageBus
from pearscaff.prompts import load as load_prompt
from pearscaff.tools import BaseTool, ToolRegistry


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


class LookupEmailTool(BaseTool):
    """Worker uses this to look up previously stored emails."""

    name = "lookup_email"
    description = (
        "Look up a previously stored email by its record ID. "
        "Returns the full email details (sender, subject, body, date)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "record_id": {
                "type": "string",
                "description": "The email record ID, e.g. 'email_001'",
            },
        },
        "required": ["record_id"],
    }

    def execute(self, **kwargs: Any) -> str:
        from pearscaff import store

        record_id = kwargs["record_id"]
        email = store.get_email(record_id)
        if not email:
            return f"No email found with record_id '{record_id}'."
        parts = [
            f"Record: {email['record_id']}",
            f"From: {email['sender']}",
            f"Subject: {email['subject']}",
            f"Date: {email['received_at']}",
            f"\nBody:\n{email['body']}",
        ]
        return "\n".join(parts)


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
                "description": "The record ID to classify, e.g. 'email_001'",
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
        from pearscaff import store

        ok = store.classify_record(
            record_id=kwargs["record_id"],
            classification=kwargs["classification"],
            reason=kwargs["reason"],
            human_context=kwargs.get("human_context", ""),
        )
        if not ok:
            return f"Failed to classify {kwargs['record_id']} — record not found."
        return f"Record {kwargs['record_id']} classified as {kwargs['classification']}."


class LookupIssueTool(BaseTool):
    """Worker uses this to look up previously stored issues."""

    name = "lookup_issue"
    description = (
        "Look up a previously stored Linear issue by its record ID. "
        "Returns the full issue details (title, status, priority, assignee)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "record_id": {
                "type": "string",
                "description": "The issue record ID, e.g. 'issue_001'",
            },
        },
        "required": ["record_id"],
    }

    def execute(self, **kwargs: Any) -> str:
        from pearscaff import store

        record_id = kwargs["record_id"]
        issue = store.get_issue(record_id)
        if not issue:
            return f"No issue found with record_id '{record_id}'."
        parts = [
            f"Record: {issue['record_id']}",
            f"Identifier: {issue['identifier']}",
            f"Title: {issue['title']}",
            f"Status: {issue['status']}",
            f"Priority: {issue['priority']}",
        ]
        if issue.get("assignee"):
            parts.append(f"Assignee: {issue['assignee']}")
        if issue.get("project"):
            parts.append(f"Project: {issue['project']}")
        if issue.get("url"):
            parts.append(f"URL: {issue['url']}")
        return "\n".join(parts)


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
    registry.register(LookupEmailTool())
    registry.register(LookupIssueTool())
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
