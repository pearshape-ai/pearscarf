"""Linear expert connector — entry point.

Exposes start(bus): the always-running process that owns Linear access.
Pushes new issue and issue_change records onto PearScarf's bus and listens
for write-back messages (create issue, update status, comment, etc.).
"""

from __future__ import annotations


def start(bus) -> None:
    """Start the Linear connector. Subscribes to the bus and begins polling."""
    raise NotImplementedError("linearscarf connector not yet implemented")
