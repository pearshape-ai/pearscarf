"""Gmail API client and OAuth helpers.

GmailAPIClient wraps the Google Gmail API for read and write operations:
list_unread, read_email, search, mark_as_read. It owns auth and token
refresh.

run_oauth_flow() drives the one-time OAuth consent flow and prints the
refresh token for the operator to add to .env.
"""

from __future__ import annotations

import base64
import json

from pearscarf import config, log


class GmailAPIClient:
    """Gmail API client using OAuth2 credentials.

    Provides list_unread, read_email, search, and mark_as_read operations
    via the Gmail API. Refreshes its token automatically when expired.
    """

    def __init__(
        self, client_id: str, client_secret: str, refresh_token: str
    ) -> None:
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
            self._service.users()
            .messages()
            .list(
                userId="me",
                q="is:unread",
                maxResults=max_results,
            )
            .execute()
        )
        messages = resp.get("messages", [])
        results = []
        for msg_stub in messages:
            msg = self.read_email(msg_stub["id"])
            if msg:
                results.append(msg)
        return results

    def read_email(self, message_id: str) -> dict | None:
        self._ensure_valid()
        msg = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
        body = self._extract_body(msg["payload"])
        return {
            "message_id": msg["id"],
            "sender": headers.get("from", ""),
            "recipient": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "body": body,
            "received_at": headers.get("date", ""),
            "raw": json.dumps(msg),
        }

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        self._ensure_valid()
        resp = (
            self._service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = resp.get("messages", [])
        results = []
        for msg_stub in messages:
            msg = self.read_email(msg_stub["id"])
            if msg:
                results.append(msg)
        return results

    def mark_as_read(self, message_id: str) -> None:
        self._ensure_valid()
        self._service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()

    def _extract_body(self, payload: dict) -> str:
        """Extract plain text body from Gmail message payload."""
        if payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode(
                "utf-8", errors="replace"
            )
        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get(
                "data"
            ):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode(
                    "utf-8", errors="replace"
                )
        # Fallback: try first part with data
        for part in parts:
            if part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode(
                    "utf-8", errors="replace"
                )
        return ""


def has_credentials() -> bool:
    """True if Gmail OAuth credentials are present in the environment."""
    return bool(
        config.GMAIL_CLIENT_ID
        and config.GMAIL_CLIENT_SECRET
        and config.GMAIL_REFRESH_TOKEN
    )


def create_client() -> GmailAPIClient | None:
    """Build a GmailAPIClient from env credentials. Returns None if missing or fails."""
    if not has_credentials():
        return None
    try:
        client = GmailAPIClient(
            client_id=config.GMAIL_CLIENT_ID,
            client_secret=config.GMAIL_CLIENT_SECRET,
            refresh_token=config.GMAIL_REFRESH_TOKEN,
        )
        log.write("gmail_expert", "--", "action", "Gmail API client initialised")
        return client
    except Exception as e:
        log.write("gmail_expert", "--", "error", f"Gmail API client init failed: {e}")
        return None


def run_oauth_flow() -> None:
    """Run the Gmail OAuth2 flow to obtain a refresh token.

    Opens a browser for Google consent, receives the callback,
    and prints the refresh token for the user to add to .env.
    """
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise SystemExit(
            "google-auth-oauthlib is required for OAuth. "
            "Install with: uv add google-auth-oauthlib"
        )

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
