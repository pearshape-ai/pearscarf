"""Gmail writer — handles write-back requests received from the bus.

GmailWriter exposes write-back operations the gmail expert may be asked
to perform: send_reply, create_draft, mark_as_read. The connector
subscribes to the bus and routes write-back messages here.

Unsupported operations return a structured graceful decline
({"ok": false, "supported": false, "reason": "..."}). The writer never
raises on a missing capability — only on actual API errors.
"""

from __future__ import annotations

from gmailscarf.connector.api_client import GmailAPIClient


def _decline(action: str, reason: str = "not supported yet") -> dict:
    return {
        "ok": False,
        "supported": False,
        "action": action,
        "reason": reason,
    }


def _ok(action: str, **payload) -> dict:
    return {"ok": True, "supported": True, "action": action, **payload}


class GmailWriter:
    """Handles Gmail write-back requests routed from the bus."""

    def __init__(self, client: GmailAPIClient) -> None:
        self._client = client

    def send_reply(self, record_id: str, body: str) -> dict:
        """Send a reply on the Gmail thread for a given record. Stub for now."""
        return _decline("send_reply")

    def create_draft(self, record_id: str, body: str) -> dict:
        """Create a draft reply on the Gmail thread for a given record. Stub for now."""
        return _decline("create_draft")

    def mark_as_read(self, message_id: str) -> dict:
        """Mark a Gmail message as read."""
        try:
            self._client.mark_as_read(message_id)
            return _ok("mark_as_read", message_id=message_id)
        except Exception as exc:
            return {
                "ok": False,
                "supported": True,
                "action": "mark_as_read",
                "reason": f"Gmail API error: {exc}",
            }

    def handle(self, action: str, **kwargs) -> dict:
        """Dispatch a write-back action by name. Returns a graceful decline if unknown."""
        method = getattr(self, action, None)
        if method is None or action.startswith("_"):
            return _decline(action, reason=f"unknown action '{action}'")
        return method(**kwargs)
