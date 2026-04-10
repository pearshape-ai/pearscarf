"""Gmail API client and tool definitions.

GmailConnect holds the authenticated API client and exposes tools the
LLM agent uses to read, search, and reply to emails. The module-level
`get_tools(ctx)` is what pearscarf calls at startup.
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Any

from pearscarf.tools import BaseTool

if TYPE_CHECKING:
    from pearscarf.expert_context import ExpertContext


# --- Gmail API client ---


class GmailAPIClient:
    """Thin wrapper around the Google Gmail API."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str) -> None:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token",
        )
        creds.refresh(Request())
        self._service = build("gmail", "v1", credentials=creds)
        self._creds = creds

    def _ensure_valid(self) -> None:
        if self._creds.expired:
            from google.auth.transport.requests import Request
            self._creds.refresh(Request())

    def list_unread(self, max_results: int = 10) -> list[dict]:
        self._ensure_valid()
        resp = (
            self._service.users().messages()
            .list(userId="me", q="is:unread", maxResults=max_results)
            .execute()
        )
        results = []
        for stub in resp.get("messages", []):
            msg = self.read_email(stub["id"])
            if msg:
                results.append(msg)
        return results

    def read_email(self, message_id: str) -> dict | None:
        self._ensure_valid()
        msg = (
            self._service.users().messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
        body = self._extract_body(msg["payload"])
        return {
            "message_id": msg["id"],
            "thread_id": msg.get("threadId", ""),
            "sender": headers.get("from", ""),
            "recipients": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "body": body,
            "received_at": headers.get("date", ""),
            "raw": json.dumps(msg),
        }

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        self._ensure_valid()
        resp = (
            self._service.users().messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        results = []
        for stub in resp.get("messages", []):
            msg = self.read_email(stub["id"])
            if msg:
                results.append(msg)
        return results

    def mark_as_read(self, message_id: str) -> None:
        self._ensure_valid()
        self._service.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]},
        ).execute()

    def _extract_body(self, payload: dict) -> str:
        if payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        for part in parts:
            if part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        return ""


# --- Connect class ---


class GmailConnect:
    """Authenticated Gmail client + tool factory.

    Shared by both the LLM agent (via get_tools) and the ingester
    (via fetch_new). One API client, one auth, no duplication.
    """

    def __init__(self, ctx: ExpertContext) -> None:
        self._ctx = ctx
        self._client: GmailAPIClient | None = None

    def _ensure_client(self) -> GmailAPIClient:
        if self._client is None:
            cfg = self._ctx.config
            client_id = cfg.get("GMAIL_CLIENT_ID", "")
            client_secret = cfg.get("GMAIL_CLIENT_SECRET", "")
            refresh_token = cfg.get("GMAIL_REFRESH_TOKEN", "")
            if not (client_id and client_secret and refresh_token):
                raise RuntimeError("Gmail OAuth credentials missing from config")
            self._client = GmailAPIClient(client_id, client_secret, refresh_token)
        return self._client

    def fetch_new(self, max_results: int = 20) -> list[dict]:
        """Fetch unread emails. Used by the ingester."""
        return self._ensure_client().list_unread(max_results)

    def get_tools(self) -> list[BaseTool]:
        """Return the list of BaseTool instances for the LLM agent."""
        return [
            ListUnreadTool(self),
            ReadEmailTool(self),
            SearchEmailTool(self),
            MarkAsReadTool(self),
            SaveEmailTool(self),
        ]


# --- Tools ---


class ListUnreadTool(BaseTool):
    name = "gmail_list_unread"
    description = "List unread emails from Gmail. Returns subjects, senders, and IDs."
    input_schema = {
        "type": "object",
        "properties": {
            "max_results": {"type": "integer", "description": "Max emails to return (default 10)"},
        },
    }

    def __init__(self, connect: GmailConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        try:
            emails = self._connect._ensure_client().list_unread(kwargs.get("max_results", 10))
            if not emails:
                return "No unread emails found."
            lines = [
                f"ID: {e['message_id']}\nFrom: {e['sender']}\nSubject: {e['subject']}\nDate: {e['received_at']}"
                for e in emails
            ]
            return f"Found {len(lines)} unread emails:\n\n" + "\n---\n".join(lines)
        except Exception as exc:
            return f"Gmail API error: {exc}"


class ReadEmailTool(BaseTool):
    name = "gmail_read_email"
    description = "Read a specific email by its Gmail message ID. Returns full content."
    input_schema = {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "Gmail message ID"},
        },
        "required": ["message_id"],
    }

    def __init__(self, connect: GmailConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        try:
            email = self._connect._ensure_client().read_email(kwargs["message_id"])
            if not email:
                return f"Email {kwargs['message_id']} not found."
            body = email["body"]
            if len(body) > 5000:
                body = body[:5000] + "\n... (truncated)"
            return (
                f"From: {email['sender']}\nTo: {email['recipients']}\n"
                f"Subject: {email['subject']}\nDate: {email['received_at']}\n\n"
                f"Body:\n{body}"
            )
        except Exception as exc:
            return f"Gmail API error: {exc}"


class SearchEmailTool(BaseTool):
    name = "gmail_search"
    description = "Search emails using Gmail search syntax (e.g. 'from:john@example.com', 'subject:invoice')."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Gmail search query"},
            "max_results": {"type": "integer", "description": "Max results (default 10)"},
        },
        "required": ["query"],
    }

    def __init__(self, connect: GmailConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        try:
            emails = self._connect._ensure_client().search(kwargs["query"], kwargs.get("max_results", 10))
            if not emails:
                return f"No emails found for: {kwargs['query']}"
            lines = [
                f"ID: {e['message_id']}\nFrom: {e['sender']}\nSubject: {e['subject']}\nDate: {e['received_at']}"
                for e in emails
            ]
            return f"Found {len(lines)} emails:\n\n" + "\n---\n".join(lines)
        except Exception as exc:
            return f"Gmail API error: {exc}"


class MarkAsReadTool(BaseTool):
    name = "gmail_mark_as_read"
    description = "Mark a specific email as read in Gmail."
    input_schema = {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "Gmail message ID to mark as read"},
        },
        "required": ["message_id"],
    }

    def __init__(self, connect: GmailConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        try:
            self._connect._ensure_client().mark_as_read(kwargs["message_id"])
            return f"Email {kwargs['message_id']} marked as read."
        except Exception as exc:
            return f"Gmail API error: {exc}"


class SaveEmailTool(BaseTool):
    name = "save_email"
    description = "Save an email to the system of record for future reference and deduplication."
    input_schema = {
        "type": "object",
        "properties": {
            "sender": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "message_id": {"type": "string", "description": "Gmail message ID for dedup"},
            "received_at": {"type": "string"},
            "recipients": {"type": "string"},
        },
        "required": ["sender", "subject", "body"],
    }

    def __init__(self, connect: GmailConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        raw = f"From: {kwargs['sender']}\nSubject: {kwargs['subject']}\n\n{kwargs['body']}"
        metadata = {
            "message_id": kwargs.get("message_id", ""),
            "sender": kwargs["sender"],
            "recipients": kwargs.get("recipients", ""),
            "subject": kwargs["subject"],
            "received_at": kwargs.get("received_at", ""),
        }
        rid = self._connect._ctx.storage.save_record(
            "email", raw, metadata, dedup_key=kwargs.get("message_id"),
        )
        if rid is None:
            return "Duplicate email — already stored."
        return f"Email saved as {rid}."


# --- Entry points ---


def get_tools(ctx: ExpertContext) -> GmailConnect:
    """Module-level entry point. Pearscarf calls this at startup."""
    return GmailConnect(ctx)


def run_oauth_flow() -> None:
    """Run the Gmail OAuth2 flow to obtain a refresh token."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise SystemExit(
            "google-auth-oauthlib is required for OAuth. "
            "Install with: uv add google-auth-oauthlib"
        )

    from pearscarf import config

    if not config.GMAIL_CLIENT_ID or not config.GMAIL_CLIENT_SECRET:
        raise SystemExit(
            "Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env before running --auth.\n"
            "Get these from Google Cloud Console → APIs & Services → Credentials."
        )

    client_config = {
        "installed": {
            "client_id": config.GMAIL_CLIENT_ID,
            "client_secret": config.GMAIL_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(
        client_config,
        scopes=["https://www.googleapis.com/auth/gmail.modify"],
    )
    creds = flow.run_local_server(port=8080)

    print("\nRefresh token obtained. Add this to your .env:\n")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print("\nOnce added, restart PearScarf to use API-based Gmail access.")
