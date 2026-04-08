"""Gmail tools exposed to the LLM agent.

These BaseTool subclasses are the surface the gmail expert agent uses to
read, search, and write Gmail. They wrap GmailAPIClient and Writer
operations.

PearScarf does not auto-discover these yet — that is the registry's job
in a follow-up. For now they are defined and importable, ready to be
wired up once the registry can introspect a connector for its tools.
"""

from __future__ import annotations

from typing import Any

from pearscarf.storage import store
from pearscarf.tools import BaseTool

from gmailscarf.connector.api_client import GmailAPIClient
from gmailscarf.connector.writer import GmailWriter


class GmailGetUnreadTool(BaseTool):
    name = "gmail_get_unread"
    description = (
        "List unread emails from Gmail via API. "
        "Returns subjects, senders, and snippets of unread messages."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "max_results": {
                "type": "integer",
                "description": "Maximum number of unread emails to return (default 10)",
            },
        },
    }

    def __init__(self, client: GmailAPIClient) -> None:
        self._client = client

    def execute(self, **kwargs: Any) -> str:
        try:
            max_results = kwargs.get("max_results", 10)
            emails = self._client.list_unread(max_results=max_results)
            if not emails:
                return "No unread emails found."
            results = []
            for e in emails:
                results.append(
                    f"ID: {e['message_id']}\n"
                    f"From: {e['sender']}\n"
                    f"Subject: {e['subject']}\n"
                    f"Date: {e['received_at']}"
                )
            return f"Found {len(results)} unread emails:\n\n" + "\n---\n".join(results)
        except Exception as exc:
            return f"Gmail API error: {exc}"


class GmailReadEmailTool(BaseTool):
    name = "gmail_read_email"
    description = (
        "Read a specific email by its Gmail message ID via API. "
        "Returns the full email content including sender, subject, and body."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "message_id": {
                "type": "string",
                "description": "Gmail message ID to read",
            },
        },
        "required": ["message_id"],
    }

    def __init__(self, client: GmailAPIClient) -> None:
        self._client = client

    def execute(self, **kwargs: Any) -> str:
        try:
            email = self._client.read_email(kwargs["message_id"])
            if not email:
                return f"Email {kwargs['message_id']} not found."
            body = email["body"]
            if len(body) > 5000:
                body = body[:5000] + "\n... (truncated)"
            return (
                f"From: {email['sender']}\n"
                f"To: {email['recipient']}\n"
                f"Subject: {email['subject']}\n"
                f"Date: {email['received_at']}\n"
                f"\nBody:\n{body}"
            )
        except Exception as exc:
            return f"Gmail API error: {exc}"


class GmailSearchTool(BaseTool):
    name = "gmail_search"
    description = (
        "Search emails in Gmail via API using Gmail search syntax. "
        "Examples: 'from:john@example.com', 'subject:invoice', 'after:2026/01/01'."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Gmail search query",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results (default 10)",
            },
        },
        "required": ["query"],
    }

    def __init__(self, client: GmailAPIClient) -> None:
        self._client = client

    def execute(self, **kwargs: Any) -> str:
        try:
            max_results = kwargs.get("max_results", 10)
            emails = self._client.search(kwargs["query"], max_results=max_results)
            if not emails:
                return f"No emails found for query: {kwargs['query']}"
            results = []
            for e in emails:
                results.append(
                    f"ID: {e['message_id']}\n"
                    f"From: {e['sender']}\n"
                    f"Subject: {e['subject']}\n"
                    f"Date: {e['received_at']}"
                )
            return f"Found {len(results)} emails:\n\n" + "\n---\n".join(results)
        except Exception as exc:
            return f"Gmail API error: {exc}"


class GmailMarkAsReadTool(BaseTool):
    name = "gmail_mark_as_read"
    description = "Mark a specific email as read in Gmail via API."
    input_schema = {
        "type": "object",
        "properties": {
            "message_id": {
                "type": "string",
                "description": "Gmail message ID to mark as read",
            },
        },
        "required": ["message_id"],
    }

    def __init__(self, writer: GmailWriter) -> None:
        self._writer = writer

    def execute(self, **kwargs: Any) -> str:
        result = self._writer.mark_as_read(kwargs["message_id"])
        if result["ok"]:
            return f"Email {kwargs['message_id']} marked as read."
        return f"Mark-as-read failed: {result['reason']}"


class GmailSendReplyTool(BaseTool):
    name = "gmail_send_reply"
    description = (
        "Send a reply on a Gmail thread for a saved email record. "
        "Returns a structured response indicating success or graceful decline."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "record_id": {
                "type": "string",
                "description": "PearScarf record_id for the email being replied to",
            },
            "body": {
                "type": "string",
                "description": "Reply body text",
            },
        },
        "required": ["record_id", "body"],
    }

    def __init__(self, writer: GmailWriter) -> None:
        self._writer = writer

    def execute(self, **kwargs: Any) -> str:
        result = self._writer.send_reply(kwargs["record_id"], kwargs["body"])
        if result["ok"]:
            return f"Reply sent on {kwargs['record_id']}."
        return f"Reply not sent: {result['reason']}"


class SaveEmailTool(BaseTool):
    name = "save_email"
    description = (
        "Save an email to the system of record for future reference and deduplication. "
        "Call this after reading an email. Returns the record_id (e.g. 'email_001') "
        "or indicates the email is a duplicate."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "sender": {
                "type": "string",
                "description": "Sender name and email, e.g. 'John <john@example.com>'",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line",
            },
            "body": {
                "type": "string",
                "description": "Email body text",
            },
            "message_id": {
                "type": "string",
                "description": "Gmail's unique message ID, used for deduplication",
            },
            "received_at": {
                "type": "string",
                "description": "Date the email was received",
            },
            "recipient": {
                "type": "string",
                "description": "Recipient email address",
            },
        },
        "required": ["sender", "subject", "body"],
    }

    def execute(self, **kwargs: Any) -> str:
        record_id = store.save_email(
            source="gmail_expert",
            sender=kwargs["sender"],
            subject=kwargs["subject"],
            body=kwargs["body"],
            message_id=kwargs.get("message_id"),
            recipient=kwargs.get("recipient", ""),
            received_at=kwargs.get("received_at", ""),
        )
        if record_id is None:
            return "Duplicate email — already stored in the system of record."
        return f"Email saved as {record_id}."


def build_tools(client: GmailAPIClient, writer: GmailWriter) -> list[BaseTool]:
    """Build the full set of Gmail tools for the LLM agent.

    Called by the registry once it can wire an expert agent to its tools.
    """
    return [
        GmailGetUnreadTool(client),
        GmailReadEmailTool(client),
        GmailSearchTool(client),
        GmailMarkAsReadTool(writer),
        GmailSendReplyTool(writer),
        SaveEmailTool(),
    ]
