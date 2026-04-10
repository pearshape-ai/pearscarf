"""Gmail background ingestion loop.

Polls Gmail for new unread emails, saves each as a record via
ctx.storage.save_record(), and notifies the worker via the bus.
"""

from __future__ import annotations

import json
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pearscarf.expert_context import ExpertContext


def start(ctx: ExpertContext) -> None:
    """Start the Gmail ingestion loop as a daemon thread."""
    from gmailscarf.gmail_connect import GmailConnect

    connect = GmailConnect(ctx)
    interval = int(ctx.config.get("GMAIL_POLL_INTERVAL", "300"))

    def _loop() -> None:
        while True:
            try:
                _poll_once(connect, ctx)
            except Exception as exc:
                ctx.log.write(ctx.expert_name, "error", f"Gmail poll failed: {exc}")
            time.sleep(interval)

    thread = threading.Thread(target=_loop, daemon=True, name="gmailscarf-ingest")
    thread.start()
    ctx.log.write(ctx.expert_name, "action", f"Gmail ingestion started (interval={interval}s)")


def _poll_once(connect, ctx: ExpertContext) -> None:
    """Fetch unread emails, save new ones, notify the worker."""
    emails = connect.fetch_new()
    for email in emails:
        # raw = true source data from the Gmail API
        raw = email.get("raw", json.dumps(email))

        # content = LLM-ready formatted string for extraction
        content = (
            f"From: {email['sender']}\n"
            f"To: {email.get('recipients', '')}\n"
            f"Subject: {email['subject']}\n"
            f"Date: {email.get('received_at', '')}\n\n"
            f"{email['body']}"
        )
        metadata = {
            "message_id": email["message_id"],
            "thread_id": email.get("thread_id", ""),
            "sender": email["sender"],
            "recipients": email.get("recipients", ""),
            "subject": email["subject"],
            "received_at": email.get("received_at", ""),
        }
        rid = ctx.storage.save_record(
            "email", raw, content=content, metadata=metadata,
            dedup_key=email["message_id"],
        )
        if not rid:
            continue

        session_id = ctx.bus.create_session(f"New email from {email['sender']}")
        ctx.bus.send(
            session_id=session_id,
            to_agent="worker",
            content=(
                f"New email from {email['sender']}\n"
                f"Subject: \"{email['subject']}\"\n"
                f"Record: {rid}\n\n"
                f"Is this relevant and why?"
            ),
        )
        ctx.log.write(ctx.expert_name, "action", f"Ingested {rid} from {email['sender']}")
