"""Intent records — CRUD over the `intent_details` sidecar table.

Intents are records with `op_area="intent"`. Records stay immutable;
`intent_details` holds the mutable per-intent state — status, parent,
type, last-set audit. All inserts to `records` for intents go through
`submit_intent` so the sidecar row is created atomically.
"""

from __future__ import annotations

import uuid

from psycopg.types.json import Jsonb

from pearscarf.storage.db import _get_conn, init_db

VALID_STATUSES = ("todo", "in_progress", "done", "cancelled")
VALID_INTENT_TYPES = ("executor", "coordinator")


class IntentError(ValueError):
    """Raised on invalid intent operations (bad status, cycle, missing parent)."""


def _next_intent_id() -> str:
    return f"intent_{uuid.uuid4().hex[:8]}"


def submit_intent(
    body: str,
    parent_record_id: str | None = None,
    intent_type: str = "executor",
    owner: str | None = None,
    owner_role: str | None = None,
    depends_on: list[str] | None = None,
    set_by: str | None = None,
) -> str:
    """Atomically insert the records row + initial `intent_details` row.

    `intent_type` is the dispatch lifecycle — `"executor"` (default; runs
    once, completes) or `"coordinator"` (parent of children; wakes when
    children complete to re-evaluate). Immutable after submit. Validated
    against `VALID_INTENT_TYPES`.

    Returns the new intent record id. Raises `IntentError` for invalid
    `intent_type`, invalid `parent_record_id` (missing or cancelled),
    missing `depends_on` ids, or any sidecar constraint violation.
    """
    init_db()

    if not body or not body.strip():
        raise IntentError("body is empty")

    if intent_type not in VALID_INTENT_TYPES:
        raise IntentError(f"intent_type must be one of {VALID_INTENT_TYPES}, got {intent_type!r}")

    deps = list(depends_on or [])

    with _get_conn() as conn:
        if parent_record_id is not None:
            _assert_parent_eligible(conn, parent_record_id)
        if deps:
            _assert_dependencies_exist(conn, deps)

        record_id = _next_intent_id()
        conn.execute(
            "INSERT INTO records "
            "(id, type, source, created_at, raw, content, metadata, "
            "expert_name, expert_version, indexed, classification) "
            "VALUES (%s, %s, %s, now(), %s, %s, %s, %s, %s, TRUE, 'relevant')",
            (
                record_id,
                "intent",
                set_by or "operator",
                body,
                body,
                Jsonb({"op_area": "intent"}),
                "records",
                "",
            ),
        )
        conn.execute(
            "INSERT INTO intent_details "
            "(intent_record_id, status, parent_record_id, intent_type, "
            "owner, owner_role, depends_on, set_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                record_id,
                "todo",
                parent_record_id,
                intent_type,
                owner,
                owner_role,
                deps,
                set_by,
            ),
        )
        conn.commit()
        return record_id


def get_intent(record_id: str, with_children: bool = False) -> dict | None:
    """Fetch the record + sidecar state. With `with_children`, also include
    direct children (depth=1)."""
    init_db()
    with _get_conn() as conn:
        row = conn.execute(_SELECT_INTENT_BY_ID, (record_id,)).fetchone()
        if row is None:
            return None
        intent = _row_to_intent(row)
        if with_children:
            children = conn.execute(
                _SELECT_INTENT_LIST + " WHERE d.parent_record_id = %s ORDER BY r.created_at",
                (record_id,),
            ).fetchall()
            intent["children"] = [_row_to_intent(c) for c in children]
        return intent


def get_intent_tree(root_record_id: str) -> dict | None:
    """Recursive walk from a root intent down. Returns the root with nested
    `children` lists, or None if the root doesn't exist."""
    init_db()
    with _get_conn() as conn:
        root = conn.execute(_SELECT_INTENT_BY_ID, (root_record_id,)).fetchone()
        if root is None:
            return None
        all_descendants = conn.execute(
            "WITH RECURSIVE descendants AS ("
            f"  {_SELECT_INTENT_LIST} WHERE d.parent_record_id = %s"
            "  UNION ALL"
            f"  {_SELECT_INTENT_LIST} JOIN descendants p ON d.parent_record_id = p.id"
            ") SELECT * FROM descendants",
            (root_record_id,),
        ).fetchall()

    nodes: dict[str, dict] = {root["id"]: _row_to_intent(root)}
    for row in all_descendants:
        nodes[row["id"]] = _row_to_intent(row)
    for node in nodes.values():
        node["children"] = []
    for node in nodes.values():
        parent_id = node.get("parent_record_id")
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(node)
    return nodes[root_record_id]


def query_intents(
    status: str | None = None,
    parent_record_id: str | None = None,
    intent_type: str | None = None,
    owner: str | None = None,
    owner_role: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Filtered list. Returns record summary + state per match."""
    init_db()
    where_parts: list[str] = []
    params: list = []
    if status:
        where_parts.append("d.status = %s")
        params.append(status)
    if parent_record_id:
        where_parts.append("d.parent_record_id = %s")
        params.append(parent_record_id)
    if intent_type:
        where_parts.append("d.intent_type = %s")
        params.append(intent_type)
    if owner:
        where_parts.append("d.owner = %s")
        params.append(owner)
    if owner_role:
        where_parts.append("d.owner_role = %s")
        params.append(owner_role)
    if since:
        where_parts.append("r.created_at >= %s")
        params.append(since)
    where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    params.append(limit)

    sql = _SELECT_INTENT_LIST + where_clause + " ORDER BY r.created_at DESC LIMIT %s"

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_intent(r) for r in rows]


def set_intent_status(record_id: str, status: str, set_by: str | None = None) -> None:
    if status not in VALID_STATUSES:
        raise IntentError(f"status must be one of {VALID_STATUSES}, got {status!r}")
    _update_sidecar(record_id, "status", status, set_by)


def set_intent_parent(
    record_id: str, parent_record_id: str | None, set_by: str | None = None
) -> None:
    init_db()
    with _get_conn() as conn:
        if parent_record_id is not None:
            if parent_record_id == record_id:
                raise IntentError("intent cannot be its own parent")
            _assert_parent_eligible(conn, parent_record_id)
            if _would_form_cycle(conn, record_id, parent_record_id):
                raise IntentError(
                    f"re-parenting {record_id} under {parent_record_id} would form a cycle"
                )
        conn.execute(
            "UPDATE intent_details "
            "SET parent_record_id = %s, set_at = now(), set_by = %s "
            "WHERE intent_record_id = %s",
            (parent_record_id, set_by, record_id),
        )
        conn.commit()


def set_intent_owner(record_id: str, owner: str | None, set_by: str | None = None) -> None:
    _update_sidecar(record_id, "owner", owner, set_by)


def set_intent_owner_role(
    record_id: str, owner_role: str | None, set_by: str | None = None
) -> None:
    _update_sidecar(record_id, "owner_role", owner_role, set_by)


def set_intent_dependencies(
    record_id: str, depends_on: list[str], set_by: str | None = None
) -> None:
    """Replace the depends_on array. Rejects cycles and missing referent intents."""
    init_db()
    deps = list(depends_on or [])
    with _get_conn() as conn:
        if deps:
            _assert_dependencies_exist(conn, deps)
            if _would_form_dep_cycle(conn, record_id, deps):
                raise IntentError(f"setting dependencies {deps} on {record_id} would form a cycle")
        result = conn.execute(
            "UPDATE intent_details SET depends_on = %s, set_at = now(), set_by = %s "
            "WHERE intent_record_id = %s",
            (deps, set_by, record_id),
        )
        if result.rowcount == 0:
            raise IntentError(f"no intent with id {record_id!r}")
        conn.commit()


# --- internals ---


_SELECT_INTENT_BY_ID = (
    "SELECT r.id, r.type, r.source, r.created_at, r.raw, r.content, r.metadata, "
    "d.status, d.parent_record_id, d.intent_type, "
    "d.owner, d.owner_role, d.depends_on, d.set_at, d.set_by "
    "FROM records r JOIN intent_details d ON d.intent_record_id = r.id "
    "WHERE r.id = %s"
)

_SELECT_INTENT_LIST = (
    "SELECT r.id, r.type, r.source, r.created_at, r.raw, r.content, r.metadata, "
    "d.status, d.parent_record_id, d.intent_type, "
    "d.owner, d.owner_role, d.depends_on, d.set_at, d.set_by "
    "FROM records r JOIN intent_details d ON d.intent_record_id = r.id"
)


def _row_to_intent(row) -> dict:
    d = dict(row)
    return {
        "id": d["id"],
        "body": d.get("content") or d.get("raw") or "",
        "status": d.get("status"),
        "parent_record_id": d.get("parent_record_id"),
        "intent_type": d.get("intent_type"),
        "owner": d.get("owner"),
        "owner_role": d.get("owner_role"),
        "depends_on": list(d.get("depends_on") or []),
        "created_at": d.get("created_at"),
        "set_at": d.get("set_at"),
        "set_by": d.get("set_by"),
        "source": d.get("source") or "",
    }


def _update_sidecar(record_id: str, field: str, value, set_by: str | None) -> None:
    init_db()
    with _get_conn() as conn:
        result = conn.execute(
            f"UPDATE intent_details SET {field} = %s, set_at = now(), set_by = %s "
            "WHERE intent_record_id = %s",
            (value, set_by, record_id),
        )
        if result.rowcount == 0:
            raise IntentError(f"no intent with id {record_id!r}")
        conn.commit()


def _assert_parent_eligible(conn, parent_record_id: str) -> None:
    """Parent must be an existing intent that hasn't been cancelled."""
    row = conn.execute(
        "SELECT status FROM intent_details WHERE intent_record_id = %s",
        (parent_record_id,),
    ).fetchone()
    if row is None:
        raise IntentError(f"parent intent {parent_record_id!r} not found")
    if row["status"] == "cancelled":
        raise IntentError(
            f"parent intent {parent_record_id!r} is cancelled — un-cancel it before adding children"
        )


def _assert_dependencies_exist(conn, deps: list[str]) -> None:
    """Every referenced intent must exist (status not checked)."""
    rows = conn.execute(
        "SELECT intent_record_id FROM intent_details WHERE intent_record_id = ANY(%s)",
        (deps,),
    ).fetchall()
    found = {r["intent_record_id"] for r in rows}
    missing = [d for d in deps if d not in found]
    if missing:
        raise IntentError(f"dependency intents not found: {missing}")


def _would_form_dep_cycle(conn, record_id: str, new_deps: list[str]) -> bool:
    """Walk depends_on from each candidate dep. Cycle if record_id is reachable."""
    for dep in new_deps:
        if dep == record_id:
            return True
        stack: list[str] = [dep]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current == record_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            row = conn.execute(
                "SELECT depends_on FROM intent_details WHERE intent_record_id = %s",
                (current,),
            ).fetchone()
            if row:
                stack.extend(row["depends_on"] or [])
    return False


def _would_form_cycle(conn, record_id: str, proposed_parent: str) -> bool:
    """Walk up from proposed_parent. If we hit record_id, re-parenting would cycle."""
    current: str | None = proposed_parent
    seen: set[str] = set()
    while current is not None:
        if current == record_id:
            return True
        if current in seen:  # defensive — pre-existing cycle in the data
            return True
        seen.add(current)
        row = conn.execute(
            "SELECT parent_record_id FROM intent_details WHERE intent_record_id = %s",
            (current,),
        ).fetchone()
        current = row["parent_record_id"] if row else None
    return False
