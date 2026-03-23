"""Thread-safe agent activity registry.

Agents update their status here so the REPL can display
what's happening in real time.
"""

from __future__ import annotations

import threading
import time

_activity: dict[str, tuple[str, str, float]] = {}
# key: "agent:session" → (agent_name, status_text, start_timestamp)
_lock = threading.Lock()


def set_status(agent: str, session: str, text: str) -> None:
    """Mark an agent as active in a session."""
    with _lock:
        _activity[f"{agent}:{session}"] = (agent, text, time.monotonic())


def clear_status(agent: str, session: str) -> None:
    """Mark an agent as idle."""
    with _lock:
        _activity.pop(f"{agent}:{session}", None)


def get_activity(session: str) -> tuple[str, str, float] | None:
    """Get the most recent active agent for a session.

    Returns (agent, text, elapsed_seconds) or None.
    """
    now = time.monotonic()
    with _lock:
        latest: tuple[str, str, float] | None = None
        for key, (agent, text, start) in _activity.items():
            if key.endswith(f":{session}"):
                elapsed = now - start
                if latest is None or start > latest[2]:
                    latest = (agent, text, elapsed)
        # Re-compute elapsed from start time, not from latest tuple
        if latest is not None:
            agent, text, elapsed = latest
            return (agent, text, elapsed)
    return None
