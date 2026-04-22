"""Gmail background ingestion loop.

Polls Gmail for new unread emails and saves each as a record via
ctx.storage.save_record(). Records land with classification=pending_triage;
the triage agent picks them up via queue polling. This ingester does
not touch the bus.
"""

from __future__ import annotations

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
    """Fetch unread emails and save new ones as records."""
    emails = connect.fetch_new()
    for email in emails:
        rid = connect.ingest_record(email)
        if not rid:
            continue
        ctx.log.write(ctx.expert_name, "action", f"Ingested {rid} from {email['sender']}")
