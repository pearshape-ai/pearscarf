from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from pearscaff.agents.expert import ExpertAgent
from pearscaff.tools import BaseTool, ToolRegistry

STORAGE_STATE_PATH = Path("storage_state.json")

GMAIL_SYSTEM_PROMPT = """\
You are a Gmail expert agent. You operate Gmail through a headless browser.

Your job is to navigate Gmail's web UI, read emails, and perform actions the user asks for.
You have browser tools to interact with pages and Gmail-specific tools for common operations.

When navigating Gmail:
- Gmail's URL is https://mail.google.com
- The inbox is the default view
- Emails appear as rows in the inbox list
- Clicking an email opens it in a detail view
- Use the browser tools to inspect the page when unsure about selectors

System of Record:
- After reading an email, ALWAYS save it using the save_email tool before replying.
- Include the record_id from save_email in your reply so the worker can reference it.
- If save_email returns that the email is a duplicate, note the existing record.

IMPORTANT: You MUST use the reply tool to send your results back. \
Your text responses are only logged internally — nobody sees them unless you use reply.

- When you finish your task, use reply(content=...) with your results.
- Do NOT send pleasantries, thank-yous, or farewells. Just deliver results.
- Use reply exactly once per request. After replying, your work is done.

Session errors:
- If a tool returns a "session expired" error, immediately reply with that error \
message so the worker can inform the human. Do not try to recover or retry.

Other notes:
- When you discover useful selectors, navigation patterns, or timing info, save them
  with the save_knowledge tool so you can work more efficiently next time.
- If something doesn't work as expected, try alternative approaches and record what you learn.
"""


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
    "Run 'pearscaff expert gmail --login' to re-authenticate."
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
        from pearscaff import store

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


def create_gmail_expert(
    on_tool_call=None, on_text=None, on_tool_result=None
) -> tuple[ExpertAgent, BrowserManager]:
    """Create a GmailExpert agent with browser tools (for direct/standalone use)."""
    if not STORAGE_STATE_PATH.exists():
        raise SystemExit(
            "No saved Gmail session. Run 'pearscaff expert gmail --login' first."
        )

    manager = BrowserManager(headed=False)
    manager.launch()

    registry = ToolRegistry()
    _register_gmail_tools(registry, manager.get_page)

    agent = ExpertAgent(
        domain="gmail",
        domain_prompt=GMAIL_SYSTEM_PROMPT,
        tool_registry=registry,
        on_tool_call=on_tool_call,
        on_text=on_text,
        on_tool_result=on_tool_result,
    )

    return agent, manager


def create_gmail_expert_for_runner(
    bus: "MessageBus | None" = None,
) -> tuple[callable, BrowserManager]:
    """Create a factory function for the AgentRunner + a BrowserManager.

    Returns (agent_factory, manager). The factory creates a new ExpertAgent
    per session, all sharing the same browser.
    """
    if not STORAGE_STATE_PATH.exists():
        raise SystemExit(
            "No saved Gmail session. Run 'pearscaff expert gmail --login' first."
        )

    manager = BrowserManager(headed=False)
    # Don't launch here — launch lazily on the runner thread
    # to avoid Playwright's greenlet thread-affinity error.

    def factory(session_id: str) -> ExpertAgent:
        registry = ToolRegistry()
        _register_gmail_tools(registry, manager.get_page)
        agent = ExpertAgent(
            domain="gmail",
            domain_prompt=GMAIL_SYSTEM_PROMPT,
            tool_registry=registry,
            bus=bus,
            agent_name="gmail_expert",
        )
        return agent

    return factory, manager
