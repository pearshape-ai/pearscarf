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

System of Record:
- Emails read by the gmail_expert are stored with a record_id (e.g. "email_001").
- You can look up previously stored emails using the lookup_email tool.

Email Triage:
When you receive an email from the gmail_expert (containing a record_id), classify it:

1. Use search_entities to check if the sender is a known entity in the graph.
2. If sender is a known entity -> auto-classify as "relevant" using classify_record. \
Tell the human: "Relevant: Email from X 'Subject' -- reason"
3. If the email has obvious noise signals (no-reply address, unsubscribe, promotional \
keywords) -> auto-classify as "noise". Tell the human: "Noise: Email from X 'Subject' -- reason"
4. If uncertain -> present the email snippet to the human and ask "Is this relevant and why?"
5. When the human responds to a classification question, use classify_record with their \
reasoning and any additional context they provide.
6. If the human disagrees with an auto-classification, reclassify with classify_record.

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
        from pearscaff import graph

        results = graph.search_entities(
            query=kwargs["query"],
            entity_type=kwargs.get("entity_type"),
        )
        if not results:
            return f"No entities found matching '{kwargs['query']}'."
        lines = []
        for ent in results:
            meta = ", ".join(f"{k}={v}" for k, v in ent["metadata"].items()) if ent["metadata"] else ""
            lines.append(f"{ent['id']} ({ent['type']}): {ent['name']}" + (f" [{meta}]" if meta else ""))
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
    registry.register(ClassifyRecordTool())
    registry.register(SearchEntitiesTool())

    agent = BaseAgent(
        tool_registry=registry,
        system_prompt=WORKER_SYSTEM_PROMPT,
        on_tool_call=on_tool_call,
        on_text=on_text,
        on_tool_result=on_tool_result,
    )
    agent._send_tool = send_tool
    return agent
