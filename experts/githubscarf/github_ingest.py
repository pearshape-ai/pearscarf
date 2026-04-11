"""GitHub background ingestion loop.

Polls GitHub for new PRs and issues, saves each as a record via
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
    """Start the GitHub ingestion loop as a daemon thread."""
    from githubscarf.github_connect import GitHubConnect

    connect = GitHubConnect(ctx)
    interval = int(ctx.config.get("GITHUB_POLL_INTERVAL", "300"))

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
                ctx.log.write(ctx.expert_name, "error", f"GitHub poll failed: {exc}")
            time.sleep(interval)

    thread = threading.Thread(target=_loop, daemon=True, name="githubscarf-ingest")
    thread.start()
    ctx.log.write(ctx.expert_name, "action", f"GitHub ingestion started (interval={interval}s)")


def _initial_sync(connect, ctx: ExpertContext) -> None:
    """Bulk-load open PRs and issues, post batch triage to worker."""
    prs = connect.list_prs(state="open")
    issues = connect.list_issues(state="open")

    new_records: list[tuple[str, str, dict]] = []  # (rid, type_label, data)
    for pr in prs:
        rid = connect.ingest_pr(pr)
        if rid:
            new_records.append((rid, "PR", pr))
    for issue in issues:
        rid = connect.ingest_issue(issue)
        if rid:
            new_records.append((rid, "Issue", issue))

    if not new_records:
        return

    session_id = ctx.bus.create_session(f"Initial GitHub sync: {len(new_records)} records")
    lines = [
        f"Initial GitHub sync loaded {len(new_records)} records.\n",
        "Summary for triage:\n",
    ]
    for rid, type_label, item in new_records:
        lines.append(
            f"- {rid} | {type_label} #{item.get('number', '')} — "
            f"{item.get('title', '')} ({item.get('state', '')})"
        )
    ctx.bus.send(
        session_id=session_id,
        to_agent="worker",
        content="\n".join(lines),
    )
    ctx.log.write(ctx.expert_name, "action", f"Initial sync: {len(new_records)} records sent for triage")


def _incremental_sync(connect, ctx: ExpertContext, synced_at: str) -> None:
    """Fetch updated PRs and issues since last sync."""
    prs = connect.list_prs_since(synced_at)
    issues = connect.list_issues_since(synced_at)

    for pr in prs:
        rid = connect.ingest_pr(pr)
        if rid:
            session_id = ctx.bus.create_session(f"New PR #{pr.get('number', '')}: {pr.get('title', '')}")
            ctx.bus.send(
                session_id=session_id,
                to_agent="worker",
                content=(
                    f"New GitHub PR #{pr.get('number', '')}\n"
                    f"Title: \"{pr.get('title', '')}\"\n"
                    f"Author: {pr.get('author', '')}\n"
                    f"Branch: {pr.get('branch', '')} → {pr.get('base_branch', '')}\n"
                    f"Record: {rid}\n\n"
                    f"Is this relevant and why?"
                ),
            )

    for issue in issues:
        rid = connect.ingest_issue(issue)
        if rid:
            session_id = ctx.bus.create_session(f"New issue #{issue.get('number', '')}: {issue.get('title', '')}")
            ctx.bus.send(
                session_id=session_id,
                to_agent="worker",
                content=(
                    f"New GitHub issue #{issue.get('number', '')}\n"
                    f"Title: \"{issue.get('title', '')}\"\n"
                    f"Author: {issue.get('author', '')}\n"
                    f"Record: {rid}\n\n"
                    f"Is this relevant and why?"
                ),
            )
