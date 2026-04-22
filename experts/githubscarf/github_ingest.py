"""GitHub background ingestion loop.

Polls GitHub for new PRs and issues and saves each as a record via
ctx.storage.save_record(). Records land with classification=pending_triage;
the triage agent picks them up via queue polling. This ingester does
not touch the bus.
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
    """Bulk-load open PRs and issues as records."""
    prs = connect.list_prs(state="open")
    issues = connect.list_issues(state="open")

    pr_count = sum(1 for pr in prs if connect.ingest_pr(pr))
    issue_count = sum(1 for issue in issues if connect.ingest_issue(issue))

    if pr_count or issue_count:
        ctx.log.write(
            ctx.expert_name, "action",
            f"Initial sync: {pr_count} PR(s), {issue_count} issue(s) saved as records",
        )


def _incremental_sync(connect, ctx: ExpertContext, synced_at: str) -> None:
    """Fetch updated PRs and issues since last sync and save as records."""
    prs = connect.list_prs_since(synced_at)
    issues = connect.list_issues_since(synced_at)

    for pr in prs:
        rid = connect.ingest_pr(pr)
        if rid:
            ctx.log.write(
                ctx.expert_name, "action",
                f"Ingested PR #{pr.get('number', '')} as {rid}",
            )

    for issue in issues:
        rid = connect.ingest_issue(issue)
        if rid:
            ctx.log.write(
                ctx.expert_name, "action",
                f"Ingested issue #{issue.get('number', '')} as {rid}",
            )
