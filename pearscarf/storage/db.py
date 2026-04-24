from __future__ import annotations

import atexit
import threading
from contextlib import contextmanager
from datetime import UTC, datetime

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
    human_context TEXT
);

CREATE INDEX IF NOT EXISTS idx_records_type ON records(type);
CREATE INDEX IF NOT EXISTS idx_records_indexed ON records(indexed);
CREATE INDEX IF NOT EXISTS idx_records_dedup ON records(dedup_key) WHERE dedup_key IS NOT NULL;

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

-- Observability: one row per Consumer boot (see notion/design/observability-and-safety.md)
CREATE TABLE IF NOT EXISTS runtimes (
    id TEXT PRIMARY KEY,
    consumer TEXT NOT NULL,
    pearscarf_version TEXT NOT NULL,
    expert_versions JSONB NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    hostname TEXT,
    pid INT
);

-- Observability: deduped system prompts referenced by llm_calls
CREATE TABLE IF NOT EXISTS llm_prompts (
    hash TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Observability: one row per LLM API call (one turn of one agent run)
CREATE TABLE IF NOT EXISTS llm_calls (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    runtime_id TEXT NOT NULL REFERENCES runtimes(id),
    consumer TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    pearscarf_version TEXT NOT NULL,

    run_id TEXT NOT NULL,
    turn_index INT NOT NULL,

    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_hash TEXT NOT NULL REFERENCES llm_prompts(hash),
    stop_reason TEXT NOT NULL,
    tool_calls JSONB,

    input_tokens INT NOT NULL,
    output_tokens INT NOT NULL,
    cache_creation_tokens INT NOT NULL DEFAULT 0,
    cache_read_tokens INT NOT NULL DEFAULT 0,
    latency_ms INT,

    record_id TEXT,
    session_id TEXT,

    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_consumer_time ON llm_calls(consumer, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_calls_run ON llm_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_record ON llm_calls(record_id) WHERE record_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_llm_calls_session ON llm_calls(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_llm_calls_version_time ON llm_calls(pearscarf_version, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_calls_model_time ON llm_calls(provider, model, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_calls_runtime ON llm_calls(runtime_id);
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
    return datetime.now(UTC).isoformat()


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
