from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

from pearscaff.config import DB_PATH

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH, timeout=10)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=5000")
    return _local.conn


def init_db() -> None:
    conn = _get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            initiated_by TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            from_agent TEXT NOT NULL,
            to_agent TEXT NOT NULL,
            content TEXT NOT NULL,
            reasoning TEXT NOT NULL DEFAULT '',
            data TEXT NOT NULL DEFAULT '{}',
            read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_messages_to_unread
            ON messages(to_agent, read);
        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, created_at);

        CREATE TABLE IF NOT EXISTS discord_threads (
            session_id TEXT PRIMARY KEY REFERENCES sessions(id),
            thread_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL
        );
        """
    )
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_session_id() -> str:
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) as c FROM sessions").fetchone()
    num = row["c"] + 1
    return f"ses_{num:03d}"


def create_session(initiated_by: str, summary: str = "") -> str:
    conn = _get_conn()
    session_id = _next_session_id()
    conn.execute(
        "INSERT INTO sessions (id, initiated_by, summary, created_at) VALUES (?, ?, ?, ?)",
        (session_id, initiated_by, summary, _now()),
    )
    conn.commit()
    return session_id


def list_sessions() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, initiated_by, summary, created_at FROM sessions ORDER BY created_at"
    ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, initiated_by, summary, created_at FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    return dict(row) if row else None


def insert_message(
    session_id: str,
    from_agent: str,
    to_agent: str,
    content: str,
    reasoning: str = "",
    data: dict | None = None,
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO messages (session_id, from_agent, to_agent, content, reasoning, data, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            from_agent,
            to_agent,
            content,
            reasoning,
            json.dumps(data or {}),
            _now(),
        ),
    )
    conn.commit()
    return cur.lastrowid


def poll_unread(to_agent: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, session_id, from_agent, to_agent, content, reasoning, data, created_at "
        "FROM messages WHERE to_agent = ? AND read = 0 ORDER BY created_at",
        (to_agent,),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_read(msg_id: int) -> None:
    conn = _get_conn()
    conn.execute("UPDATE messages SET read = 1 WHERE id = ?", (msg_id,))
    conn.commit()


def get_history(session_id: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, from_agent, to_agent, content, reasoning, data, created_at "
        "FROM messages WHERE session_id = ? ORDER BY created_at",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# Discord thread mapping

def save_thread_mapping(session_id: str, thread_id: int, channel_id: int) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO discord_threads (session_id, thread_id, channel_id) VALUES (?, ?, ?)",
        (session_id, thread_id, channel_id),
    )
    conn.commit()


def get_session_by_thread(thread_id: int) -> str | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT session_id FROM discord_threads WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()
    return row["session_id"] if row else None


def get_thread_by_session(session_id: str) -> int | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT thread_id FROM discord_threads WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return row["thread_id"] if row else None
