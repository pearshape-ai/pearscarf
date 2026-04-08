"""Linear polling loop — auth, retry, fetch new issues and changes."""

from __future__ import annotations


def poll(bus) -> None:
    """Poll Linear for new issues and changes and push them onto the bus."""
    raise NotImplementedError("linearscarf poller not yet implemented")
