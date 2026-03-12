from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

_LOGS_DIR = Path("data/logs")
_LOG_FILE = _LOGS_DIR / "session.log"
_lock = threading.Lock()
_initialized = False


def _ensure_dir() -> None:
    global _initialized
    if not _initialized:
        _LOGS_DIR.mkdir(exist_ok=True)
        _initialized = True


def write(
    agent: str,
    session: str | None,
    entry_type: str,
    message: str,
) -> None:
    """Append a single log entry. Thread-safe, append-only."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ses = session or "--"
    line = f"[{ts}] [{agent}] [{ses}] [{entry_type}] {message}\n"
    with _lock:
        _ensure_dir()
        with open(_LOG_FILE, "a") as f:
            f.write(line)
