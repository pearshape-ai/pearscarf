"""Gmail background ingestion — `GmailIngest` consumer.

Polls Gmail for new unread emails and saves each as a record via
`ctx.storage.save_record()`. Records land with
`classification=pending_triage`; Triage picks them up via queue polling.
This ingester does not touch the bus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pearscarf.consumer import Consumer

if TYPE_CHECKING:
    from pearscarf.expert_context import ExpertContext


class GmailIngest(Consumer):
    """Consumer that polls Gmail and saves new emails as records."""

    name = "gmailscarf"
    default_poll_interval = 300.0

    def __init__(self, ctx: "ExpertContext", poll_interval: float | None = None) -> None:
        from gmailscarf.gmail_connect import GmailConnect

        if poll_interval is None:
            poll_interval = float(ctx.config.get("GMAIL_POLL_INTERVAL", self.default_poll_interval))
        super().__init__(poll_interval=poll_interval)

        self._ctx = ctx
        self._connect = GmailConnect(ctx)
        self._pending: list = []

    def _next(self):
        if self._pending:
            return self._pending.pop(0)
        emails = self._connect.fetch_new()
        if not emails:
            return None
        self._pending = list(emails)
        return self._pending.pop(0) if self._pending else None

    def _handle(self, email) -> None:
        rid = self._connect.ingest_record(email)
        if not rid:
            return
        self._ctx.log.write(
            self._ctx.expert_name, "action",
            f"Ingested {rid} from {email['sender']}",
        )


def start(ctx: "ExpertContext"):
    """Entry point called by the expert registry. Returns the polling thread."""
    consumer = GmailIngest(ctx)
    consumer.start()
    ctx.log.write(
        ctx.expert_name, "action",
        f"Gmail ingestion started (interval={int(consumer._poll_interval)}s)",
    )
    return consumer._thread
