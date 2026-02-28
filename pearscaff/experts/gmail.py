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

Important:
- Always print email contents (subject, sender, date, body) to the user clearly.
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
            raise RuntimeError("Browser not launched. Call launch() first.")
        return self._page

    def save_state(self) -> None:
        if self._context:
            self._context.storage_state(path=str(STORAGE_STATE_PATH))

    def close(self) -> None:
        if self._context:
            self.save_state()
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()


def login(headed: bool = True) -> None:
    """Open a visible browser for the user to log into Gmail."""
    manager = BrowserManager(headed=headed)
    manager.launch()
    page = manager.get_page()
    page.goto("https://mail.google.com")
    print("Browser opened. Please log into Gmail.")
    print("Press Enter here once you're logged in...")
    input()
    manager.save_state()
    manager.close()
    print(f"Session saved to {STORAGE_STATE_PATH}")


def create_gmail_expert(
    on_tool_call=None, on_text=None, on_tool_result=None
) -> tuple[ExpertAgent, BrowserManager]:
    """Create a GmailExpert agent with browser tools."""
    if not STORAGE_STATE_PATH.exists():
        raise SystemExit(
            "No saved Gmail session. Run 'pearscaff expert gmail --login' first."
        )

    manager = BrowserManager(headed=False)
    manager.launch()

    registry = ToolRegistry()

    # Register browser tools
    get_page = manager.get_page
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

    agent = ExpertAgent(
        domain="gmail",
        domain_prompt=GMAIL_SYSTEM_PROMPT,
        tool_registry=registry,
        on_tool_call=on_tool_call,
        on_text=on_text,
        on_tool_result=on_tool_result,
    )

    return agent, manager
