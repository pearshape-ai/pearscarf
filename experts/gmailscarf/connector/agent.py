"""Gmail expert connector — entry point.

Exposes start(bus): the always-running process that owns Gmail access.
Pushes new email records onto PearScarf's bus and listens for write-back
messages (replies, mark-as-read, etc.).
"""

from __future__ import annotations


def start(bus) -> None:
    """Start the Gmail connector. Subscribes to the bus and begins polling."""
    raise NotImplementedError("gmailscarf connector not yet implemented")
