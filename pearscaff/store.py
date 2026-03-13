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
            "e.sender, e.subject, e.body "
            "FROM records r LEFT JOIN emails e ON r.id = e.record_id "
            "WHERE r.classification IS NULL "
            "ORDER BY r.created_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
