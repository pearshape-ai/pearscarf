"""System of Record — persistent structured storage for domain data.

Each expert agent owns writing to its domain tables.
The worker reads from storage for context.
"""

from __future__ import annotations

from pearscaff.db import _get_conn, _now, init_db


def _next_email_id() -> str:
    with _get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM records WHERE type = 'email'").fetchone()
        num = row["c"] + 1
        return f"email_{num:03d}"


def save_email(
    source: str,
    sender: str,
    subject: str,
    body: str,
    message_id: str | None = None,
    recipient: str = "",
    received_at: str = "",
    raw: str = "",
) -> str | None:
    """Save an email to the SOR.

    Returns record_id (e.g. "email_001"), or None if duplicate (same message_id).
    """
    init_db()
    with _get_conn() as conn:
        # Dedup on message_id
        if message_id:
            existing = conn.execute(
                "SELECT record_id FROM emails WHERE message_id = %s",
                (message_id,),
            ).fetchone()
            if existing:
                return None

        record_id = _next_email_id()
        now = _now()

        conn.execute(
            "INSERT INTO records (id, type, source, created_at, raw) VALUES (%s, %s, %s, %s, %s)",
            (record_id, "email", source, now, raw),
        )
        conn.execute(
            "INSERT INTO emails (record_id, message_id, sender, recipient, subject, body, received_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (record_id, message_id, sender, recipient, subject, body, received_at or now),
        )
        conn.commit()
        return record_id


def get_email(record_id: str) -> dict | None:
    """Look up an email by record_id."""
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT e.record_id, e.message_id, e.sender, e.recipient, e.subject, e.body, "
            "e.received_at, r.source, r.created_at "
            "FROM emails e JOIN records r ON e.record_id = r.id "
            "WHERE e.record_id = %s",
            (record_id,),
        ).fetchone()
        return dict(row) if row else None


def get_email_by_message_id(message_id: str) -> dict | None:
    """Look up an email by Gmail message ID."""
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT e.record_id, e.message_id, e.sender, e.recipient, e.subject, e.body, "
            "e.received_at, r.source, r.created_at "
            "FROM emails e JOIN records r ON e.record_id = r.id "
            "WHERE e.message_id = %s",
            (message_id,),
        ).fetchone()
        return dict(row) if row else None


def list_emails(limit: int = 20) -> list[dict]:
    """List recent emails from the SOR."""
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT e.record_id, e.message_id, e.sender, e.recipient, e.subject, "
            "e.received_at, r.source, r.created_at "
            "FROM emails e JOIN records r ON e.record_id = r.id "
            "ORDER BY r.created_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# --- Issues ---


def _next_issue_id() -> str:
    with _get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM records WHERE type = 'issue'").fetchone()
        num = row["c"] + 1
        return f"issue_{num:03d}"


def save_issue(
    source: str,
    linear_id: str,
    identifier: str = "",
    title: str = "",
    description: str = "",
    status: str = "",
    priority: str = "",
    assignee: str = "",
    project: str = "",
    labels: list[str] | None = None,
    comments: list[dict] | None = None,
    url: str = "",
    linear_created_at: str = "",
    linear_updated_at: str = "",
    raw: str = "",
) -> tuple[str, bool]:
    """Save or update an issue in the SOR.

    Returns (record_id, is_new). If the issue already exists (same linear_id),
    updates its fields and returns (existing_record_id, False).
    """
    init_db()
    from psycopg.types.json import Jsonb

    with _get_conn() as conn:
        # Check for existing issue
        existing = conn.execute(
            "SELECT record_id FROM issues WHERE linear_id = %s",
            (linear_id,),
        ).fetchone()

        if existing:
            record_id = existing["record_id"]
            conn.execute(
                "UPDATE issues SET identifier = %s, title = %s, description = %s, "
                "status = %s, priority = %s, assignee = %s, project = %s, "
                "labels = %s, comments = %s, url = %s, linear_updated_at = %s "
                "WHERE record_id = %s",
                (identifier, title, description, status, priority, assignee, project,
                 Jsonb(labels or []), Jsonb(comments or []), url,
                 linear_updated_at or None, record_id),
            )
            conn.commit()
            return record_id, False

        record_id = _next_issue_id()
        now = _now()

        conn.execute(
            "INSERT INTO records (id, type, source, created_at, raw) VALUES (%s, %s, %s, %s, %s)",
            (record_id, "issue", source, now, raw),
        )
        conn.execute(
            "INSERT INTO issues (record_id, linear_id, identifier, title, description, status, "
            "priority, assignee, project, labels, comments, url, "
            "linear_created_at, linear_updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (record_id, linear_id, identifier, title, description, status, priority,
             assignee, project, Jsonb(labels or []), Jsonb(comments or []), url,
             linear_created_at or None, linear_updated_at or None),
        )
        conn.commit()
        return record_id, True


def get_issue(record_id: str) -> dict | None:
    """Look up an issue by record_id."""
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT i.record_id, i.linear_id, i.identifier, i.title, i.description, "
            "i.status, i.priority, i.assignee, i.project, i.labels, i.comments, "
            "i.url, i.linear_created_at, i.linear_updated_at, r.source, r.created_at "
            "FROM issues i JOIN records r ON i.record_id = r.id "
            "WHERE i.record_id = %s",
            (record_id,),
        ).fetchone()
        return dict(row) if row else None


def get_issue_by_linear_id(linear_id: str) -> dict | None:
    """Look up an issue by Linear's unique ID."""
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT i.record_id, i.linear_id, i.identifier, i.title, i.description, "
            "i.status, i.priority, i.assignee, i.project, i.labels, i.comments, "
            "i.url, i.linear_created_at, i.linear_updated_at, r.source, r.created_at "
            "FROM issues i JOIN records r ON i.record_id = r.id "
            "WHERE i.linear_id = %s",
            (linear_id,),
        ).fetchone()
        return dict(row) if row else None


def list_issues(limit: int = 20) -> list[dict]:
    """List recent issues from the SOR."""
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT i.record_id, i.linear_id, i.identifier, i.title, i.description, "
            "i.status, i.priority, i.assignee, i.project, i.labels, i.comments, "
            "i.url, i.linear_updated_at, r.source, r.created_at "
            "FROM issues i JOIN records r ON i.record_id = r.id "
            "ORDER BY r.created_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def classify_record(
    record_id: str,
    classification: str,
    reason: str = "",
    human_context: str = "",
) -> bool:
    """Set classification on a record. Returns True if updated."""
    init_db()
    with _get_conn() as conn:
        cur = conn.execute(
            "UPDATE records SET classification = %s, classification_reason = %s, human_context = %s "
            "WHERE id = %s",
            (classification, reason, human_context, record_id),
        )
        conn.commit()
        return cur.rowcount > 0


def get_pending_records(limit: int = 10) -> list[dict]:
    """Get unclassified records (classification IS NULL)."""
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT r.id, r.type, r.source, r.created_at, "
            "e.sender, e.subject, e.body, "
            "i.identifier, i.title AS issue_title, i.status AS issue_status, "
            "i.priority AS issue_priority, i.assignee AS issue_assignee "
            "FROM records r "
            "LEFT JOIN emails e ON r.id = e.record_id "
            "LEFT JOIN issues i ON r.id = i.record_id "
            "WHERE r.classification IS NULL "
            "ORDER BY r.created_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
