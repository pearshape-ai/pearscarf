"""Gmail polling loop — auth, retry, fetch new messages."""

from __future__ import annotations


def poll(bus) -> None:
    """Poll Gmail for new messages and push them onto the bus."""
    raise NotImplementedError("gmailscarf poller not yet implemented")
