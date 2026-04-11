from __future__ import annotations

import atexit
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from pearscarf.config import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        conninfo = (
            f"host={POSTGRES_HOST} port={POSTGRES_PORT} "
            f"dbname={POSTGRES_DB} user={POSTGRES_USER} password={POSTGRES_PASSWORD} "
            f"connect_timeout=5"
        )
        _pool = ConnectionPool(
            conninfo,
            min_size=1,
            max_size=10,
            timeout=10.0,
            kwargs={"row_factory": dict_row, "autocommit": False},
            open=False,
        )
        _pool.open(wait=False)
        atexit.register(close_pool)
    return _pool


@contextmanager
def _get_conn():
    """Get a connection from the pool. Use as context manager."""
    with _get_pool().connection() as conn:
        yield conn


def close_pool() -> None:
    """Explicitly close the connection pool."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    initiated_by TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    content TEXT NOT NULL,
    reasoning TEXT NOT NULL DEFAULT '',
    data JSONB NOT NULL DEFAULT '{}',
    read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_to_unread
    ON messages(to_agent, read);
CREATE INDEX IF NOT EXISTS idx_messages_session
    ON messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS discord_threads (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    thread_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL
);

-- System of Record
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    raw TEXT,
    content TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    dedup_key TEXT,
    expert_name TEXT,
    expert_version TEXT,
    indexed BOOLEAN NOT NULL DEFAULT FALSE,
    classification TEXT,
    classification_reason TEXT,
    human_context TEXT,
    resolution_pending JSONB,
    resolution_status TEXT
);

CREATE INDEX IF NOT EXISTS idx_records_type ON records(type);
CREATE INDEX IF NOT EXISTS idx_records_indexed ON records(indexed);
CREATE INDEX IF NOT EXISTS idx_records_dedup ON records(dedup_key) WHERE dedup_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS emails (
    record_id TEXT PRIMARY KEY REFERENCES records(id),
    message_id TEXT UNIQUE,
    sender TEXT,
    recipient TEXT,
    subject TEXT,
    body TEXT,
    received_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_emails_message_id ON emails(message_id);

CREATE TABLE IF NOT EXISTS issues (
    record_id TEXT PRIMARY KEY REFERENCES records(id),
    linear_id TEXT UNIQUE NOT NULL,
    identifier TEXT,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT,
    priority TEXT,
    assignee TEXT,
    project TEXT,
    labels JSONB,
    comments JSONB,
    url TEXT,
    linear_created_at TIMESTAMPTZ,
    linear_updated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_issues_linear_id ON issues(linear_id);
CREATE INDEX IF NOT EXISTS idx_issues_identifier ON issues(identifier);

CREATE TABLE IF NOT EXISTS issue_changes (
    record_id TEXT PRIMARY KEY REFERENCES records(id),
    issue_record_id TEXT NOT NULL,
    linear_history_id TEXT UNIQUE,
    field TEXT NOT NULL,
    from_value TEXT,
    to_value TEXT,
    changed_by TEXT,
    changed_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_issue_changes_issue ON issue_changes(issue_record_id);
CREATE INDEX IF NOT EXISTS idx_issue_changes_linear_id ON issue_changes(linear_history_id);

CREATE TABLE IF NOT EXISTS curator_queue (
    record_id TEXT PRIMARY KEY,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS mcp_keys (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    revoked BOOLEAN NOT NULL DEFAULT FALSE
);

-- Expert registration
CREATE TABLE IF NOT EXISTS experts (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    source_type TEXT NOT NULL,
    package_name TEXT NOT NULL,
    install_method TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    installed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE INDEX IF NOT EXISTS idx_experts_name ON experts(name);
CREATE INDEX IF NOT EXISTS idx_experts_source_type ON experts(source_type);

CREATE TABLE IF NOT EXISTS entity_types (
    expert_id INTEGER NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    type_name TEXT NOT NULL,
    knowledge_path TEXT NOT NULL,
    PRIMARY KEY (expert_id, type_name)
);

CREATE TABLE IF NOT EXISTS identifier_patterns (
    id SERIAL PRIMARY KEY,
    expert_id INTEGER NOT NULL REFERENCES experts(id) ON DELETE CASCADE,
    pattern_or_field TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('global', 'source'))
);

CREATE INDEX IF NOT EXISTS idx_identifier_patterns_scope ON identifier_patterns(scope);

CREATE TABLE IF NOT EXISTS expert_record_schemas (
    expert_name TEXT NOT NULL,
    record_type TEXT NOT NULL,
    version TEXT NOT NULL,
    table_name TEXT NOT NULL,
    schema_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (expert_name, record_type, version)
);
"""


_db_initialized = False
_db_init_lock = threading.Lock()


def init_db() -> None:
    global _db_initialized
    if _db_initialized:
        return
    with _db_init_lock:
        if _db_initialized:
            return
        with _get_conn() as conn:
            conn.execute(_SCHEMA)
            conn.commit()
        _db_initialized = True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_session_id() -> str:
    with _get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM sessions").fetchone()
        num = row["c"] + 1
        return f"ses_{num:03d}"


def create_session(initiated_by: str, summary: str = "") -> str:
    session_id = _next_session_id()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, initiated_by, summary, created_at) VALUES (%s, %s, %s, %s)",
            (session_id, initiated_by, summary, _now()),
        )
        conn.commit()
    return session_id


def list_sessions() -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, initiated_by, summary, created_at FROM sessions ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]


def get_session(session_id: str) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, initiated_by, summary, created_at FROM sessions WHERE id = %s",
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
    with _get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO messages (session_id, from_agent, to_agent, content, reasoning, data, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                session_id,
                from_agent,
                to_agent,
                content,
                reasoning,
                Jsonb(data or {}),
                _now(),
            ),
        )
        conn.commit()
        row = cur.fetchone()
        return dict(row)["id"] if row else 0


def poll_unread(to_agent: str) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, session_id, from_agent, to_agent, content, reasoning, data, created_at "
            "FROM messages WHERE to_agent = %s AND read = FALSE ORDER BY created_at",
            (to_agent,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_read(msg_id: int) -> None:
    with _get_conn() as conn:
        conn.execute("UPDATE messages SET read = TRUE WHERE id = %s", (msg_id,))
        conn.commit()


def get_history(session_id: str) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, from_agent, to_agent, content, reasoning, data, created_at "
            "FROM messages WHERE session_id = %s ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# Discord thread mapping

def save_thread_mapping(session_id: str, thread_id: int, channel_id: int) -> None:
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO discord_threads (session_id, thread_id, channel_id) VALUES (%s, %s, %s) "
            "ON CONFLICT (session_id) DO UPDATE SET thread_id = EXCLUDED.thread_id, channel_id = EXCLUDED.channel_id",
            (session_id, thread_id, channel_id),
        )
        conn.commit()


def get_session_by_thread(thread_id: int) -> str | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT session_id FROM discord_threads WHERE thread_id = %s",
            (thread_id,),
        ).fetchone()
        return row["session_id"] if row else None


def get_thread_by_session(session_id: str) -> int | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT thread_id FROM discord_threads WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        return row["thread_id"] if row else None
