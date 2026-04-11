"""Linear background ingestion loop.

Polls Linear for new issues and changes, saves each as a record via
ctx.storage.save_record(), and notifies the worker via the bus.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pearscarf.expert_context import ExpertContext


def start(ctx: ExpertContext) -> None:
    """Start the Linear ingestion loop as a daemon thread."""
    from linearscarf.linear_connect import LinearConnect

    connect = LinearConnect(ctx)
    interval = int(ctx.config.get("LINEAR_POLL_INTERVAL", "300"))

    state = {"synced_at": None}

    def _loop() -> None:
        while True:
            try:
                if state["synced_at"] is None:
                    _initial_sync(connect, ctx)
                else:
                    _incremental_sync(connect, ctx, state["synced_at"])
                state["synced_at"] = datetime.now(timezone.utc).isoformat()
            except Exception as exc:
                ctx.log.write(ctx.expert_name, "error", f"Linear poll failed: {exc}")
            time.sleep(interval)

    thread = threading.Thread(target=_loop, daemon=True, name="linearscarf-ingest")
    thread.start()
    ctx.log.write(ctx.expert_name, "action", f"Linear ingestion started (interval={interval}s)")


def _initial_sync(connect, ctx: ExpertContext) -> None:
    """Bulk-load all issues and post one batch triage session."""
    issues = connect.list_issues()
    new_records: list[tuple[str, dict]] = []
    for issue in issues:
        rid = connect.ingest_record(issue)
        if rid:
            new_records.append((rid, issue))

    if not new_records:
        return

    session_id = ctx.bus.create_session(f"Initial Linear sync: {len(new_records)} issues")
    lines = [
        f"Initial Linear sync loaded {len(new_records)} issues.\n",
        "Here's a summary for triage — classify as relevant or noise:\n",
    ]
    for rid, iss in new_records:
        lines.append(
            f"- {rid} | {iss.get('identifier', '')} — "
            f"{iss.get('title', '')} [{iss.get('status', '')}, {iss.get('priority', '')}]"
        )
    ctx.bus.send(
        session_id=session_id,
        to_agent="worker",
        content="\n".join(lines),
    )
    ctx.log.write(
        ctx.expert_name, "action",
        f"Initial sync: {len(new_records)} new issues sent for batch triage",
    )


def _incremental_sync(connect, ctx: ExpertContext, synced_at: str) -> None:
    """Fetch updated issues, sync history changes, post per-issue sessions for new ones."""
    issues = connect.list_updated_since(synced_at)
    for issue in issues:
        rid = connect.ingest_record(issue)
        is_new = rid is not None

        # Sync history changes
        try:
            changes = connect.get_issue_history(issue["id"], since=synced_at)
            issue_record_id = rid or f"issue_{issue.get('identifier', 'unknown')}"
            saved = 0
            for change in changes:
                crid = connect.ingest_change(change, issue_record_id)
                if crid:
                    saved += 1
            if saved:
                ctx.log.write(
                    ctx.expert_name, "action",
                    f"Poll: {saved} change(s) for {issue.get('identifier', '')}",
                )
        except Exception as exc:
            ctx.log.write(
                ctx.expert_name, "error",
                f"History fetch failed for {issue.get('identifier', '')}: {exc}",
            )

        if is_new:
            session_id = ctx.bus.create_session(
                f"New issue {issue.get('identifier', '')}: {issue.get('title', '')}"
            )
            ctx.bus.send(
                session_id=session_id,
                to_agent="worker",
                content=(
                    f"New Linear issue {issue.get('identifier', '')}\n"
                    f"Title: \"{issue.get('title', '')}\"\n"
                    f"Status: {issue.get('status', '')}\n"
                    f"Priority: {issue.get('priority', '')}\n"
                    f"Record: {rid}\n\n"
                    f"Is this relevant and why?"
                ),
            )
