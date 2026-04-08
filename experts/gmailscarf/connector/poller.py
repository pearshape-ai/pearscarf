"""Gmail poller — fetches new unread messages and pushes them onto the bus.

The GmailPoller is a daemon-thread loop owned by the connector. It calls
GmailAPIClient.list_unread, dedups against the SOR, saves new messages,
and creates a worker session for each one. Auth, retries, and rate
limiting are this module's responsibility.
"""

from __future__ import annotations

import threading
import time

from pearscarf import config, log
from pearscarf.bus import MessageBus
from pearscarf.storage import store

from gmailscarf.connector.api_client import GmailAPIClient


class GmailPoller:
    """Polls Gmail for new unread messages and pushes them onto the bus."""

    def __init__(
        self,
        bus: MessageBus,
        client: GmailAPIClient,
        interval: int | None = None,
    ) -> None:
        self._bus = bus
        self._client = client
        self._interval = interval if interval is not None else config.GMAIL_POLL_INTERVAL
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> threading.Thread:
        """Start the poll loop in a daemon thread. Returns the thread."""
        self._thread = threading.Thread(
            target=self.run, daemon=True, name="gmailscarf-poller"
        )
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        """Poll loop. Runs until stop() is called."""
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                log.write("gmail_expert", "--", "error", f"Email poll failed: {exc}")
                self._notify_error(exc)
            self._stop.wait(self._interval)

    def _poll_once(self) -> None:
        unread = self._client.list_unread(max_results=20)
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
                continue  # Race condition safety

            session_id = self._bus.create_session(
                "gmail_expert",
                f"New email from {email['sender']}",
            )
            self._bus.send(
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

    def _notify_error(self, exc: Exception) -> None:
        """Surface a poll error to the human via the bus."""
        try:
            err_session = self._bus.create_session("gmail_expert", "Poll error")
            self._bus.send(
                session_id=err_session,
                from_agent="worker",
                to_agent="human",
                content=f"⚠ Email poll failed: {exc}",
            )
        except Exception:
            pass
