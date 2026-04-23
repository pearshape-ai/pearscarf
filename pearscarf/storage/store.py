"""System of Record — persistent structured storage for domain data.

Each expert agent owns writing to its domain tables.
The assistant reads from storage for context.
"""

from __future__ import annotations

from pearscarf.storage.db import _get_conn, _now, init_db


# --- Generic record API (used by ExpertContext) ---


def _next_record_id(record_type: str) -> str:
    import uuid

    return f"{record_type}_{uuid.uuid4().hex[:8]}"


def save_record(
    record_type: str,
    raw: str,
    content: str = "",
    metadata: dict | None = None,
    dedup_key: str | None = None,
    source: str = "",
    expert_name: str = "",
    expert_version: str = "",
) -> str | None:
    """Save a generic record. Returns record_id on success, None on duplicate.

    This is the single write path experts use via ExpertContext.storage.
    `raw` is the true source data (JSON, markdown, whatever came from the API).
    `content` is the LLM-ready formatted string the indexer uses for extraction.
    Dedup is based on dedup_key — if a record with the same key already
    exists, None is returned and nothing is written.
    """
    from psycopg.types.json import Jsonb

    init_db()
    with _get_conn() as conn:
        if dedup_key:
            existing = conn.execute(
                "SELECT id FROM records WHERE dedup_key = %s",
                (dedup_key,),
            ).fetchone()
            if existing:
                return None

        record_id = _next_record_id(record_type)
        conn.execute(
            "INSERT INTO records "
            "(id, type, source, created_at, raw, content, metadata, dedup_key, "
            "expert_name, expert_version) "
            "VALUES (%s, %s, %s, now(), %s, %s, %s, %s, %s, %s)",
            (
                record_id,
                record_type,
                source or expert_name,
                raw,
                content,
                Jsonb(metadata or {}),
                dedup_key,
                expert_name,
                expert_version,
            ),
        )
        # Dual-write to the expert's typed table if one exists
        if metadata:
            _dual_write(conn, record_id, record_type, metadata)
        conn.commit()
        return record_id


def get_record(record_id: str) -> dict | None:
    """Look up a record by id. Returns the row as a dict, or None."""
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, type, source, created_at, raw, content, metadata, "
            "indexed, classification, dedup_key, expert_name, expert_version "
            "FROM records WHERE id = %s",
            (record_id,),
        ).fetchone()
        return dict(row) if row else None


# --- Classification labels ---
#
# Single source of truth for records.classification values. Everywhere
# that reads or writes this column should use these constants.

RELEVANT = "relevant"
NOISE = "noise"
PENDING_TRIAGE = "pending_triage"
TRIAGING = "triaging"      # transient: triage agent is processing
UNCERTAIN = "uncertain"    # triage couldn't decide; HIL queue


def set_classification(record_id: str, label: str) -> None:
    """Set classification on a record. System-path write used by the
    framework when an expert passes a classification on save, by the
    triage agent when resolving pending_triage records, and by the
    sugar helpers below."""
    init_db()
    with _get_conn() as conn:
        conn.execute(
            "UPDATE records SET classification = %s WHERE id = %s",
            (label, record_id),
        )
        conn.commit()


def mark_relevant(record_id: str) -> None:
    """Shortcut for set_classification(id, RELEVANT)."""
    set_classification(record_id, RELEVANT)


# --- Per-type record helpers (legacy, used by existing experts) ---


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


# --- Ingest ---


def _next_ingest_id() -> str:
    with _get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM records WHERE type = 'ingest'").fetchone()
        num = row["c"] + 1
        return f"ingest_{num:03d}"


def save_ingest(
    source: str,
    raw: str,
    human_context: str = "",
) -> str:
    """Save a seed ingest record to the SOR.

    Auto-classified as relevant — bypasses triage.
    Returns record_id (e.g. 'ingest_001').
    """
    init_db()
    with _get_conn() as conn:
        record_id = _next_ingest_id()
        now = _now()

        conn.execute(
            "INSERT INTO records (id, type, source, created_at, raw, classification, human_context) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (record_id, "ingest", source, now, raw, RELEVANT, human_context or None),
        )
        conn.commit()
        return record_id


# --- Issue Changes ---


def _next_change_id() -> str:
    with _get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM records WHERE type = 'issue_change'").fetchone()
        num = row["c"] + 1
        return f"change_{num:03d}"


def save_issue_change(
    issue_record_id: str,
    field: str,
    from_value: str = "",
    to_value: str = "",
    linear_history_id: str | None = None,
    changed_by: str = "",
    changed_at: str = "",
) -> str | None:
    """Save an issue change to the SOR.

    Returns record_id (e.g. 'change_001'), or None if duplicate (same linear_history_id).
    Auto-classified as relevant since the parent issue was already triaged.
    """
    init_db()
    with _get_conn() as conn:
        # Dedup on linear_history_id
        if linear_history_id:
            existing = conn.execute(
                "SELECT record_id FROM issue_changes WHERE linear_history_id = %s",
                (linear_history_id,),
            ).fetchone()
            if existing:
                return None

        record_id = _next_change_id()
        now = _now()

        conn.execute(
            "INSERT INTO records (id, type, source, created_at, classification) "
            "VALUES (%s, %s, %s, %s, %s)",
            (record_id, "issue_change", "linear_expert", now, RELEVANT),
        )
        conn.execute(
            "INSERT INTO issue_changes (record_id, issue_record_id, linear_history_id, "
            "field, from_value, to_value, changed_by, changed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (record_id, issue_record_id, linear_history_id, field,
             from_value, to_value, changed_by, changed_at or now),
        )
        conn.commit()
        return record_id


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


# --- Curator Queue ---


def enqueue_for_curation(record_id: str) -> None:
    """Enqueue a record for curation. Idempotent — re-indexing does not reset claimed_at."""
    init_db()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO curator_queue (record_id) VALUES (%s) "
            "ON CONFLICT (record_id) DO NOTHING",
            (record_id,),
        )
        conn.commit()


# --- Communications ---


def get_communications_for_entity(name_or_email: str, since: str | None = None) -> list[dict]:
    """Find emails where the entity appears as sender or recipient."""
    init_db()
    with _get_conn() as conn:
        pattern = f"%{name_or_email}%"
        if since:
            rows = conn.execute(
                "SELECT e.record_id, e.sender, e.recipient, e.subject, "
                "e.received_at, r.source "
                "FROM emails e "
                "JOIN records r ON e.record_id = r.id "
                "WHERE (e.sender ILIKE %s OR e.recipient ILIKE %s) "
                "AND e.received_at >= %s "
                "ORDER BY e.received_at DESC LIMIT 20",
                (pattern, pattern, since),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT e.record_id, e.sender, e.recipient, e.subject, "
                "e.received_at, r.source "
                "FROM emails e "
                "JOIN records r ON e.record_id = r.id "
                "WHERE (e.sender ILIKE %s OR e.recipient ILIKE %s) "
                "ORDER BY e.received_at DESC LIMIT 20",
                (pattern, pattern),
            ).fetchall()
        return [dict(r) for r in rows]


# --- MCP Keys ---

import hashlib
import secrets


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _next_mcp_key_id() -> str:
    with _get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM mcp_keys").fetchone()
        return f"mck_{row['c'] + 1:03d}"


def create_mcp_key(name: str) -> dict:
    """Create a new MCP API key. Returns {id, name, raw_key}."""
    init_db()
    raw_key = f"psk_{secrets.token_urlsafe(32)}"
    key_hash = _hash_key(raw_key)
    key_id = _next_mcp_key_id()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO mcp_keys (id, name, key_hash) VALUES (%s, %s, %s)",
            (key_id, name, key_hash),
        )
        conn.commit()
    return {"id": key_id, "name": name, "raw_key": raw_key}


def list_mcp_keys() -> list[dict]:
    """List all MCP keys (without hashes)."""
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at, last_used_at, revoked FROM mcp_keys "
            "ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def revoke_mcp_key(key_id: str) -> bool:
    """Revoke an MCP key. Returns True if found and revoked."""
    init_db()
    with _get_conn() as conn:
        cur = conn.execute(
            "UPDATE mcp_keys SET revoked = TRUE WHERE id = %s AND revoked = FALSE",
            (key_id,),
        )
        conn.commit()
        return cur.rowcount > 0


def validate_mcp_key(raw_key: str) -> bool:
    """Validate an MCP key. Updates last_used_at if valid."""
    init_db()
    key_hash = _hash_key(raw_key)
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM mcp_keys WHERE key_hash = %s AND revoked = FALSE",
            (key_hash,),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE mcp_keys SET last_used_at = now() WHERE id = %s",
            (row["id"],),
        )
        conn.commit()
        return True



# --- Expert registration ---
#
# The experts table has one row per (name, version) combination. Multiple
# versions of the same expert can coexist; at most one is enabled at any
# time. The enabled row is the "active" version. Helpers below distinguish
# between "look up by name" (which means the active row) and "look up by
# name + version" (which can target a specific historical row).


_EXPERTS_COLUMNS = (
    "id, name, version, source_type, package_name, install_method, "
    "enabled, installed_at"
)


def list_registered_experts(enabled_only: bool = False) -> list[dict]:
    """List rows from the experts table.

    If `enabled_only` is True, only currently active rows are returned —
    one per name. Otherwise every row (every historical version) is
    returned, ordered by name then installed_at descending.
    """
    init_db()
    sql = f"SELECT {_EXPERTS_COLUMNS} FROM experts"
    if enabled_only:
        sql += " WHERE enabled = TRUE"
    sql += " ORDER BY name, installed_at DESC"
    with _get_conn() as conn:
        rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]


def get_enabled_expert(name: str) -> dict | None:
    """Return the currently enabled row for a given expert name, or None."""
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            f"SELECT {_EXPERTS_COLUMNS} FROM experts "
            "WHERE name = %s AND enabled = TRUE",
            (name,),
        ).fetchone()
        return dict(row) if row else None


def get_expert_version(name: str, version: str) -> dict | None:
    """Return the row for a specific (name, version) pair, or None."""
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            f"SELECT {_EXPERTS_COLUMNS} FROM experts "
            "WHERE name = %s AND version = %s",
            (name, version),
        ).fetchone()
        return dict(row) if row else None


def list_versions_of_expert(name: str) -> list[dict]:
    """All historical rows for a given expert name, newest installed_at first."""
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            f"SELECT {_EXPERTS_COLUMNS} FROM experts "
            "WHERE name = %s ORDER BY installed_at DESC",
            (name,),
        ).fetchall()
        return [dict(r) for r in rows]


def disable_enabled_expert(name: str) -> bool:
    """Set enabled=false on the currently enabled row of `name`. Returns True if updated."""
    init_db()
    with _get_conn() as conn:
        cur = conn.execute(
            "UPDATE experts SET enabled = FALSE "
            "WHERE name = %s AND enabled = TRUE",
            (name,),
        )
        conn.commit()
        return cur.rowcount > 0


def enable_latest_disabled_expert(name: str) -> dict | None:
    """Re-enable the most recently installed disabled row for `name`.

    Returns the row that was enabled, or None if there was nothing to
    enable.
    """
    init_db()
    with _get_conn() as conn:
        # Pick the most recently installed disabled row
        target = conn.execute(
            f"SELECT {_EXPERTS_COLUMNS} FROM experts "
            "WHERE name = %s AND enabled = FALSE "
            "ORDER BY installed_at DESC LIMIT 1",
            (name,),
        ).fetchone()
        if target is None:
            return None
        conn.execute(
            "UPDATE experts SET enabled = TRUE WHERE id = %s",
            (target["id"],),
        )
        conn.commit()
        return dict(target)


def delete_expert_cascade(name: str) -> int:
    """Delete every row for an expert by name. Cascades to entity_types and identifier_patterns.

    Returns the number of rows removed from the experts table.
    """
    init_db()
    with _get_conn() as conn:
        cur = conn.execute("DELETE FROM experts WHERE name = %s", (name,))
        conn.commit()
        return cur.rowcount


def list_entity_types_for_expert_id(expert_id: int) -> list[dict]:
    """List entity_types declared by a specific expert row (by id)."""
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT expert_id, type_name, knowledge_path FROM entity_types "
            "WHERE expert_id = %s ORDER BY type_name",
            (expert_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_entity_types_for_enabled_experts() -> list[dict]:
    """List entity_types contributed by every currently enabled expert.

    Used by the install validator to detect new_entity_type collisions
    against the active world schema. Joins entity_types → experts so
    historical (disabled) expert versions are excluded.
    """
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT e.name AS expert_name, et.type_name, et.knowledge_path "
            "FROM entity_types et "
            "JOIN experts e ON e.id = et.expert_id "
            "WHERE e.enabled = TRUE "
            "ORDER BY e.name, et.type_name"
        ).fetchall()
        return [dict(r) for r in rows]


def list_identifier_patterns_for_expert_id(expert_id: int) -> list[dict]:
    """List identifier_patterns declared by a specific expert row (by id)."""
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, expert_id, pattern_or_field, entity_type, scope "
            "FROM identifier_patterns WHERE expert_id = %s ORDER BY id",
            (expert_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def write_full_registration(
    name: str,
    version: str,
    source_type: str,
    package_name: str,
    install_method: str,
    enabled: bool,
    entity_types: list[dict],
    identifier_patterns: list[dict],
) -> int:
    """Write expert + entity_types + identifier_patterns in one transaction.

    If a row already exists for (name, version), it's replaced (along
    with its child rows). If `enabled` is True, any other enabled row for
    the same name is first disabled — there is at most one enabled row
    per name at any time.

    entity_types items: {type_name, knowledge_path}
    identifier_patterns items: {pattern_or_field, entity_type, scope}

    Returns the id of the inserted/updated experts row.
    """
    init_db()
    with _get_conn() as conn:
        # Enforce single-enabled-per-name invariant
        if enabled:
            conn.execute(
                "UPDATE experts SET enabled = FALSE "
                "WHERE name = %s AND enabled = TRUE",
                (name,),
            )

        # Upsert the (name, version) row, capturing the id
        row = conn.execute(
            "INSERT INTO experts (name, version, source_type, package_name, "
            "install_method, enabled) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (name, version) DO UPDATE SET "
            "source_type = EXCLUDED.source_type, "
            "package_name = EXCLUDED.package_name, "
            "install_method = EXCLUDED.install_method, "
            "enabled = EXCLUDED.enabled "
            "RETURNING id",
            (name, version, source_type, package_name, install_method, enabled),
        ).fetchone()
        expert_id = row["id"]

        # Replace child rows for this version
        conn.execute("DELETE FROM entity_types WHERE expert_id = %s", (expert_id,))
        conn.execute(
            "DELETE FROM identifier_patterns WHERE expert_id = %s", (expert_id,)
        )
        for et in entity_types:
            conn.execute(
                "INSERT INTO entity_types (expert_id, type_name, knowledge_path) "
                "VALUES (%s, %s, %s)",
                (expert_id, et["type_name"], et["knowledge_path"]),
            )
        for ip in identifier_patterns:
            conn.execute(
                "INSERT INTO identifier_patterns "
                "(expert_id, pattern_or_field, entity_type, scope) "
                "VALUES (%s, %s, %s, %s)",
                (expert_id, ip["pattern_or_field"], ip["entity_type"], ip["scope"]),
            )
        conn.commit()
        return expert_id



# --- Expert record schemas (typed tables) ---


import hashlib as _hashlib


_JSON_TO_PG: dict[str, str] = {
    "string": "TEXT",
    "integer": "INTEGER",
    "number": "NUMERIC",
    "boolean": "BOOLEAN",
}

# Cache: record_type -> (table_name, column_names). Populated lazily.
_active_tables: dict[str, tuple[str, list[str]]] | None = None


def _schema_hash(schema: dict) -> str:
    """Deterministic hash of a JSON Schema for change detection."""
    import json
    raw = json.dumps(schema, sort_keys=True)
    return _hashlib.sha256(raw.encode()).hexdigest()[:16]


def _version_to_suffix(version: str) -> str:
    """Convert semver to a Postgres-safe suffix: 0.1.2 -> 0_1_2."""
    return version.replace(".", "_")


def create_typed_table(
    expert_name: str,
    record_type: str,
    version: str,
    schema: dict,
) -> str:
    """Create a versioned typed table from a JSON Schema. Returns the table name.

    Table: {expert}_{type}_{version} with record_id FK to records(id)
    plus one column per schema property. Registers in expert_record_schemas.
    Idempotent — skips if the table already exists with the same schema hash.
    """
    init_db()
    table_name = f"{expert_name}_{record_type}_{_version_to_suffix(version)}"
    new_hash = _schema_hash(schema)

    with _get_conn() as conn:
        # Check if this exact version + schema already exists
        row = conn.execute(
            "SELECT schema_hash FROM expert_record_schemas "
            "WHERE expert_name = %s AND record_type = %s AND version = %s",
            (expert_name, record_type, version),
        ).fetchone()
        if row:
            existing = dict(row) if row else {}
            if existing.get("schema_hash") == new_hash:
                return table_name  # already created, same schema

        # Build CREATE TABLE from JSON Schema properties
        props = schema.get("properties", {})
        columns = ["record_id TEXT PRIMARY KEY REFERENCES records(id) ON DELETE CASCADE"]
        for col_name, col_def in props.items():
            pg_type = _JSON_TO_PG.get(col_def.get("type", "string"), "TEXT")
            columns.append(f"{col_name} {pg_type}")

        create_sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(columns)})"
        conn.execute(create_sql)

        # Register (upsert)
        conn.execute(
            "INSERT INTO expert_record_schemas "
            "(expert_name, record_type, version, table_name, schema_hash) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (expert_name, record_type, version) DO UPDATE SET "
            "table_name = EXCLUDED.table_name, schema_hash = EXCLUDED.schema_hash",
            (expert_name, record_type, version, table_name, new_hash),
        )
        conn.commit()

    # Invalidate cache so next save picks up the new table
    global _active_tables
    _active_tables = None

    return table_name


def _load_active_tables() -> dict[str, tuple[str, list[str]]]:
    """Load the latest active typed table for each record_type.

    Returns {record_type: (table_name, [column_names])}.
    Picks the most recently created entry per (expert_name, record_type).
    """
    init_db()
    result: dict[str, tuple[str, list[str]]] = {}
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT ON (expert_name, record_type) "
            "expert_name, record_type, table_name "
            "FROM expert_record_schemas "
            "ORDER BY expert_name, record_type, created_at DESC"
        ).fetchall()
        for row in rows:
            r = dict(row)
            table_name = r["table_name"]
            # Get column names from information_schema
            cols = conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = %s AND column_name != 'record_id' "
                "ORDER BY ordinal_position",
                (table_name,),
            ).fetchall()
            col_names = [dict(c)["column_name"] for c in cols]
            result[r["record_type"]] = (table_name, col_names)
    return result


def get_active_table(record_type: str) -> tuple[str, list[str]] | None:
    """Get the active typed table for a record_type. Cached after first call."""
    global _active_tables
    if _active_tables is None:
        _active_tables = _load_active_tables()
    return _active_tables.get(record_type)


def _dual_write(conn, record_id: str, record_type: str, metadata: dict) -> None:
    """Write metadata fields to the expert's typed table if one exists."""
    info = get_active_table(record_type)
    if info is None:
        return
    table_name, col_names = info
    if not col_names:
        return

    # Only write columns that exist in both metadata and the typed table
    write_cols = [c for c in col_names if c in metadata]
    if not write_cols:
        return

    cols_sql = ", ".join(["record_id"] + write_cols)
    placeholders = ", ".join(["%s"] * (1 + len(write_cols)))
    values = [record_id] + [str(metadata.get(c, "")) for c in write_cols]

    conn.execute(
        f"INSERT INTO {table_name} ({cols_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT (record_id) DO NOTHING",
        values,
    )


def list_typed_tables() -> list[str]:
    """Return all typed table names from expert_record_schemas. Used by erase_all."""
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT table_name FROM expert_record_schemas"
        ).fetchall()
        return [dict(r)["table_name"] for r in rows]


def reset_active_table_cache() -> None:
    """Drop the cached active tables. Called after install/update."""
    global _active_tables
    _active_tables = None
