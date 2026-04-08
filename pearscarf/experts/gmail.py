from __future__ import annotations

import base64
import json
import threading
import time
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from pearscarf import log
from pearscarf.agents.expert import ExpertAgent
from pearscarf.knowledge import load as load_prompt
from pearscarf.tools import BaseTool, ToolRegistry

STORAGE_STATE_PATH = Path("data/storage_state.json")

class GmailAPIClient:
    """Gmail API client using OAuth2 credentials.

    Provides list_unread, read_email, search, and mark_as_read operations
    via the Gmail API instead of a headless browser.
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


def _has_mcp_credentials() -> bool:
    from pearscarf import config

    return bool(
        config.GMAIL_CLIENT_ID
        and config.GMAIL_CLIENT_SECRET
        and config.GMAIL_REFRESH_TOKEN
    )


def _create_mcp_client() -> GmailAPIClient | None:
    """Try to create a Gmail API client. Returns None on failure."""
    from pearscarf import config

    if not _has_mcp_credentials():
        return None
    try:
        client = GmailAPIClient(
            client_id=config.GMAIL_CLIENT_ID,
            client_secret=config.GMAIL_CLIENT_SECRET,
            refresh_token=config.GMAIL_REFRESH_TOKEN,
        )
        log.write("gmail_expert", "--", "action", "MCP transport active (OAuth configured)")
        return client
    except Exception as e:
        log.write(
            "gmail_expert", "--", "error",
            f"MCP init failed: {e}, falling back to browser",
        )
        return None


# --- Browser tools ---


class BrowserNavigateTool(BaseTool):
    name = "browser_navigate"
    description = "Navigate the browser to a URL."
    input_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to navigate to"},
        },
        "required": ["url"],
    }

    def __init__(self, get_page: callable) -> None:
        self._get_page = get_page

    def execute(self, **kwargs: Any) -> str:
        page = self._get_page()
        page.goto(kwargs["url"], wait_until="domcontentloaded", timeout=30000)
        return f"Navigated to {page.url}"


class BrowserClickTool(BaseTool):
    name = "browser_click"
    description = "Click an element on the page by CSS selector."
    input_schema = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector of the element to click",
            },
        },
        "required": ["selector"],
    }

    def __init__(self, get_page: callable) -> None:
        self._get_page = get_page

    def execute(self, **kwargs: Any) -> str:
        page = self._get_page()
        page.click(kwargs["selector"], timeout=10000)
        return f"Clicked element: {kwargs['selector']}"


class BrowserTypeTool(BaseTool):
    name = "browser_type"
    description = "Type text into an input element by CSS selector."
    input_schema = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector of the input element",
            },
            "text": {"type": "string", "description": "Text to type"},
        },
        "required": ["selector", "text"],
    }

    def __init__(self, get_page: callable) -> None:
        self._get_page = get_page

    def execute(self, **kwargs: Any) -> str:
        page = self._get_page()
        page.fill(kwargs["selector"], kwargs["text"], timeout=10000)
        return f"Typed into {kwargs['selector']}"


class BrowserGetTextTool(BaseTool):
    name = "browser_get_text"
    description = (
        "Get text content from elements matching a CSS selector. "
        "Returns text from up to 20 matching elements."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector to match elements",
            },
        },
        "required": ["selector"],
    }

    def __init__(self, get_page: callable) -> None:
        self._get_page = get_page

    def execute(self, **kwargs: Any) -> str:
        page = self._get_page()
        elements = page.query_selector_all(kwargs["selector"])
        texts = []
        for el in elements[:20]:
            text = el.text_content()
            if text and text.strip():
                texts.append(text.strip())
        if not texts:
            return f"No text found for selector: {kwargs['selector']}"
        return "\n---\n".join(texts)


class BrowserScreenshotTool(BaseTool):
    name = "browser_screenshot"
    description = (
        "Take a screenshot of the current page and get a description of what's visible. "
        "Returns the page title, URL, and visible text content summary."
    )
    input_schema = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, get_page: callable) -> None:
        self._get_page = get_page

    def execute(self, **kwargs: Any) -> str:
        page = self._get_page()
        title = page.title()
        url = page.url
        # Get visible text as a summary instead of actual screenshot
        body_text = page.inner_text("body")
        # Truncate to avoid huge responses
        if len(body_text) > 3000:
            body_text = body_text[:3000] + "\n... (truncated)"
        return f"Page: {title}\nURL: {url}\n\nVisible text:\n{body_text}"


class BrowserWaitTool(BaseTool):
    name = "browser_wait"
    description = "Wait for an element matching a CSS selector to appear on the page."
    input_schema = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector to wait for",
            },
            "timeout": {
                "type": "integer",
                "description": "Max wait time in milliseconds (default 10000)",
            },
        },
        "required": ["selector"],
    }

    def __init__(self, get_page: callable) -> None:
        self._get_page = get_page

    def execute(self, **kwargs: Any) -> str:
        page = self._get_page()
        timeout = kwargs.get("timeout", 10000)
        page.wait_for_selector(kwargs["selector"], timeout=timeout)
        return f"Element appeared: {kwargs['selector']}"


class BrowserGetHtmlTool(BaseTool):
    name = "browser_get_html"
    description = (
        "Get the outer HTML of elements matching a CSS selector. "
        "Useful for inspecting page structure and finding the right selectors. "
        "Returns HTML from up to 10 matching elements."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector to match elements",
            },
        },
        "required": ["selector"],
    }

    def __init__(self, get_page: callable) -> None:
        self._get_page = get_page

    def execute(self, **kwargs: Any) -> str:
        page = self._get_page()
        elements = page.query_selector_all(kwargs["selector"])
        htmls = []
        for el in elements[:10]:
            html = el.evaluate("el => el.outerHTML")
            if html:
                # Truncate very long elements
                if len(html) > 1000:
                    html = html[:1000] + "..."
                htmls.append(html)
        if not htmls:
            return f"No elements found for selector: {kwargs['selector']}"
        return "\n---\n".join(htmls)


# --- Gmail-specific tools ---

_SESSION_EXPIRED_MSG = (
    "Gmail session expired. The browser was redirected to the Google sign-in page. "
    "Run 'pearscarf expert gmail --login' to re-authenticate."
)


def _check_session(page: Any) -> str | None:
    """Check if the browser was redirected to a login page.

    Returns an error message if session expired, None if OK.
    """
    if "accounts.google.com" in page.url:
        return _SESSION_EXPIRED_MSG
    return None


class GmailGetUnreadTool(BaseTool):
    name = "gmail_get_unread"
    description = (
        "Navigate to Gmail inbox and list unread emails. "
        "Returns subjects, senders, and snippets of unread messages."
    )
    input_schema = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, get_page: callable) -> None:
        self._get_page = get_page

    def execute(self, **kwargs: Any) -> str:
        page = self._get_page()
        page.goto(
            "https://mail.google.com/mail/u/0/#inbox",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        page.wait_for_timeout(3000)  # Gmail takes time to load

        expired = _check_session(page)
        if expired:
            return expired

        # Try to find unread email rows
        unread = page.query_selector_all("tr.zE")
        if not unread:
            # Fallback: try alternate selector
            unread = page.query_selector_all('[class*="unread"]')

        if not unread:
            return "No unread emails found, or could not locate unread email elements. Try using browser_get_text with 'body' to inspect the page."

        results = []
        for row in unread[:10]:
            text = row.text_content()
            if text and text.strip():
                results.append(text.strip())

        return f"Found {len(results)} unread emails:\n\n" + "\n---\n".join(results)


class GmailReadLatestTool(BaseTool):
    name = "gmail_read_latest"
    description = (
        "Open and read the latest unread email in Gmail. "
        "Navigates to inbox, clicks the first unread email, and extracts its content."
    )
    input_schema = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, get_page: callable) -> None:
        self._get_page = get_page

    def execute(self, **kwargs: Any) -> str:
        page = self._get_page()
        page.goto(
            "https://mail.google.com/mail/u/0/#inbox",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        page.wait_for_timeout(3000)

        expired = _check_session(page)
        if expired:
            return expired

        # Find and click first unread
        unread = page.query_selector("tr.zE")
        if not unread:
            return "No unread emails found. Inbox may be empty or selectors may have changed. Use browser_get_html to inspect."

        unread.click()
        page.wait_for_timeout(2000)

        # Extract email content
        parts = []

        # Subject
        subject_el = page.query_selector("h2.hP")
        if subject_el:
            parts.append(f"Subject: {subject_el.text_content()}")

        # Sender
        sender_el = page.query_selector("[email]")
        if sender_el:
            sender_name = sender_el.text_content() or ""
            sender_email = sender_el.get_attribute("email") or ""
            parts.append(f"From: {sender_name} <{sender_email}>")

        # Date
        date_el = page.query_selector(".g3")
        if date_el:
            parts.append(f"Date: {date_el.get_attribute('title') or date_el.text_content()}")

        # Body
        body_el = page.query_selector(".a3s")
        if body_el:
            body_text = body_el.text_content()
            if body_text and len(body_text) > 5000:
                body_text = body_text[:5000] + "\n... (truncated)"
            parts.append(f"\nBody:\n{body_text}")

        if not parts:
            # Fallback: get all visible text
            body_text = page.inner_text("body")
            if len(body_text) > 3000:
                body_text = body_text[:3000] + "..."
            return f"Could not parse email structure. Page text:\n{body_text}"

        return "\n".join(parts)


class GmailMarkAsReadTool(BaseTool):
    name = "gmail_mark_as_read"
    description = (
        "Mark the currently open email as read in Gmail. "
        "Must be called while viewing an email (after gmail_read_latest or navigating to one)."
    )
    input_schema = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, get_page: callable) -> None:
        self._get_page = get_page

    def execute(self, **kwargs: Any) -> str:
        page = self._get_page()

        expired = _check_session(page)
        if expired:
            return expired

        # Try the "More" menu -> "Mark as read" approach
        # First try the toolbar mark-as-read button
        try:
            # Look for the mark as read option in the toolbar
            # Gmail uses aria-labels
            mark_btn = page.query_selector('[aria-label="Mark as read"]')
            if mark_btn:
                mark_btn.click()
                return "Email marked as read."
        except Exception:
            pass

        # Fallback: try keyboard shortcut (Shift+I marks as read in Gmail)
        try:
            page.keyboard.press("Shift+i")
            page.wait_for_timeout(1000)
            return "Sent mark-as-read keyboard shortcut (Shift+I)."
        except Exception as exc:
            return f"Could not mark as read: {exc}. Try using browser tools to find the mark-as-read button."


# --- MCP (API-backed) tools ---


class MCPGmailGetUnreadTool(BaseTool):
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


class MCPGmailReadEmailTool(BaseTool):
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


class MCPGmailSearchTool(BaseTool):
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


class MCPGmailMarkAsReadTool(BaseTool):
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

    def __init__(self, client: GmailAPIClient) -> None:
        self._client = client

    def execute(self, **kwargs: Any) -> str:
        try:
            self._client.mark_as_read(kwargs["message_id"])
            return f"Email {kwargs['message_id']} marked as read."
        except Exception as exc:
            return f"Gmail API error: {exc}"


# --- Browser management ---


class BrowserManager:
    def __init__(self, headed: bool = False) -> None:
        self._headed = headed
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def launch(self) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=not self._headed)

        if STORAGE_STATE_PATH.exists():
            self._context = self._browser.new_context(
                storage_state=str(STORAGE_STATE_PATH)
            )
        else:
            self._context = self._browser.new_context()

        self._page = self._context.new_page()

    def get_page(self) -> Page:
        if not self._page:
            self.launch()
        return self._page

    def save_state(self) -> None:
        if self._context:
            self._context.storage_state(path=str(STORAGE_STATE_PATH))

    def close(self) -> None:
        if self._context:
            try:
                self.save_state()
            except Exception:
                # save_state may fail if called from a different thread
                # than the one that created the browser (greenlet error).
                # State was already saved during normal operation.
                pass
            try:
                self._context.close()
            except Exception:
                pass
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass


def login(headed: bool = True) -> None:
    """Open a browser for the user to log into Google.

    Uses accounts.google.com to avoid Gmail chat popups.
    After login, Google redirects to Gmail and we save the session.
    """
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()

    # Start at Google Accounts login with Gmail as the redirect target.
    # This avoids loading Gmail's UI (and its chat popups) until after login.
    page.goto(
        "https://accounts.google.com/ServiceLogin"
        "?continue=https://mail.google.com/mail/",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    print("Browser opened. Log into your Google account.")
    print("Session saves automatically once login completes.")
    print("Press Ctrl+C to cancel.\n")

    try:
        if "/mail/" not in page.url:
            print("Waiting for login...")
            page.wait_for_url("**/mail/**", timeout=300_000)

        print("Login detected! Saving session...")
        context.storage_state(path=str(STORAGE_STATE_PATH))
        print(f"Session saved to {STORAGE_STATE_PATH}")
    except KeyboardInterrupt:
        print("\nCancelled.")
    except Exception as exc:
        print(f"Error: {exc}")
    finally:
        try:
            context.close()
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass


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

    print(f"\nRefresh token obtained. Add this to your .env:\n")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print(f"\nOnce added, restart PearScarf to use API-based Gmail access.")


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
                "description": "Gmail's unique message ID (from URL hash or headers), used for deduplication",
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
        from pearscarf.storage import store

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


def _register_gmail_tools(registry: ToolRegistry, get_page: callable) -> None:
    for tool_cls in [
        BrowserNavigateTool,
        BrowserClickTool,
        BrowserTypeTool,
        BrowserGetTextTool,
        BrowserScreenshotTool,
        BrowserWaitTool,
        BrowserGetHtmlTool,
        GmailGetUnreadTool,
        GmailReadLatestTool,
        GmailMarkAsReadTool,
    ]:
        registry.register(tool_cls(get_page))
    registry.register(SaveEmailTool())


def _register_mcp_gmail_tools(registry: ToolRegistry, client: GmailAPIClient) -> None:
    registry.register(MCPGmailGetUnreadTool(client))
    registry.register(MCPGmailReadEmailTool(client))
    registry.register(MCPGmailSearchTool(client))
    registry.register(MCPGmailMarkAsReadTool(client))
    registry.register(SaveEmailTool())


def create_gmail_expert(
    on_tool_call=None, on_text=None, on_tool_result=None
) -> tuple[ExpertAgent, BrowserManager]:
    """Create a GmailExpert agent with browser tools (for direct/standalone use)."""
    if not STORAGE_STATE_PATH.exists():
        raise SystemExit(
            "No saved Gmail session. Run 'pearscarf expert gmail --login' first."
        )

    manager = BrowserManager(headed=False)
    manager.launch()

    registry = ToolRegistry()
    _register_gmail_tools(registry, manager.get_page)

    agent = ExpertAgent(
        domain="gmail",
        domain_prompt=load_prompt("gmail_browser"),
        tool_registry=registry,
        on_tool_call=on_tool_call,
        on_text=on_text,
        on_tool_result=on_tool_result,
    )

    return agent, manager


def create_gmail_expert_for_runner(
    bus: "MessageBus | None" = None,
) -> tuple[callable, BrowserManager | None, GmailAPIClient | None]:
    """Create a factory function for the AgentRunner.

    Returns (agent_factory, manager_or_none, mcp_client_or_none).
    Uses MCP (API) transport when OAuth credentials are configured,
    falls back to browser transport otherwise.
    """
    mcp_client = _create_mcp_client()

    if mcp_client:
        # MCP transport — no browser needed
        def factory(session_id: str) -> ExpertAgent:
            registry = ToolRegistry()
            _register_mcp_gmail_tools(registry, mcp_client)
            return ExpertAgent(
                domain="gmail",
                domain_prompt=load_prompt("gmail_mcp"),
                tool_registry=registry,
                bus=bus,
                agent_name="gmail_expert",
            )

        return factory, None, mcp_client

    # Browser transport fallback
    if not STORAGE_STATE_PATH.exists():
        raise SystemExit(
            "No saved Gmail session. Run 'pearscarf expert gmail --login' first.\n"
            "Or configure Gmail OAuth credentials in .env for API-based access."
        )

    log.write("gmail_expert", "--", "action", "Browser transport active (no MCP credentials)")
    manager = BrowserManager(headed=False)

    def factory(session_id: str) -> ExpertAgent:
        registry = ToolRegistry()
        _register_gmail_tools(registry, manager.get_page)
        return ExpertAgent(
            domain="gmail",
            domain_prompt=load_prompt("gmail_browser"),
            tool_registry=registry,
            bus=bus,
            agent_name="gmail_expert",
        )

    return factory, manager, None


# --- Email polling ---


def start_email_polling(
    bus: "MessageBus",
    mcp_client: GmailAPIClient,
    interval: int | None = None,
) -> threading.Thread:
    """Start a background daemon thread that polls Gmail for new unread emails.

    Each new email gets saved to the SOR and creates a session for the worker.
    Returns the thread (already started).
    """
    from pearscarf import config
    from pearscarf.storage import store

    if interval is None:
        interval = config.GMAIL_POLL_INTERVAL

    def _poll_loop() -> None:
        while True:
            try:
                unread = mcp_client.list_unread(max_results=20)
                for email in unread:
                    mid = email["message_id"]
                    existing = store.get_email_by_message_id(mid)
                    if existing:
                        continue

                    record_id = store.save_email(
                        source="gmail_expert",
                        sender=email["sender"],
                        subject=email["subject"],
                        body=email["body"],
                        message_id=mid,
                        recipient=email.get("recipient", ""),
                        received_at=email.get("received_at", ""),
                        raw=email.get("raw", ""),
                    )
                    if not record_id:
                        continue  # Duplicate (race condition safety)

                    session_id = bus.create_session(
                        "gmail_expert",
                        f"New email from {email['sender']}",
                    )
                    bus.send(
                        session_id=session_id,
                        from_agent="gmail_expert",
                        to_agent="worker",
                        content=(
                            f"New email from {email['sender']}\n"
                            f"Subject: \"{email['subject']}\"\n"
                            f"Record: {record_id}\n\n"
                            f"Is this relevant and why?"
                        ),
                    )
                    log.write(
                        "gmail_expert", session_id, "action",
                        f"Poll: new email {record_id} from {email['sender']}",
                    )
            except Exception as exc:
                log.write("gmail_expert", "--", "error", f"Email poll failed: {exc}")
                # Notify human about the error
                try:
                    err_session = bus.create_session("gmail_expert", "Poll error")
                    bus.send(
                        session_id=err_session,
                        from_agent="worker",
                        to_agent="human",
                        content=f"⚠ Email poll failed: {exc}",
                    )
                except Exception:
                    pass

            time.sleep(interval)

    thread = threading.Thread(target=_poll_loop, daemon=True, name="email-poller")
    thread.start()
    return thread
