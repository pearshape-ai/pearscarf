"""GitHub background ingestion — `GithubIngest` consumer.

Polls GitHub for new PRs and issues and saves each as a record via
`ctx.storage.save_record()`. Records land with
`classification=pending_triage`; Triage picks them up via queue
polling. This ingester does not touch the bus.

Polls run in two modes: an initial bulk load of open PRs and issues
(first cycle), and incremental sync of updated-since items each
subsequent cycle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pearscarf.consumer import Consumer

if TYPE_CHECKING:
    from pearscarf.expert_context import ExpertContext


class GithubIngest(Consumer):
    """Consumer that polls GitHub and saves PRs + issues as records."""

    name = "githubscarf"
    default_poll_interval = 300.0

    def __init__(self, ctx: "ExpertContext", poll_interval: float | None = None) -> None:
        from githubscarf.github_connect import GitHubConnect

        if poll_interval is None:
            poll_interval = float(ctx.config.get("GITHUB_POLL_INTERVAL", self.default_poll_interval))
        super().__init__(poll_interval=poll_interval)

        self._ctx = ctx
        self._connect = GitHubConnect(ctx)
        self._synced_at: str | None = None
        self._pending: list = []  # list of ("pr"|"issue", item dict)

    def _next(self):
        if self._pending:
            return self._pending.pop(0)

        cycle_started_at = datetime.now(timezone.utc).isoformat()

        if self._synced_at is None:
            # Initial sync: bulk-load open PRs and issues inline.
            prs = self._connect.list_prs(state="open")
            issues = self._connect.list_issues(state="open")

            pr_count = sum(1 for pr in prs if self._connect.ingest_pr(pr))
            issue_count = sum(1 for issue in issues if self._connect.ingest_issue(issue))

            if pr_count or issue_count:
                self._ctx.log.write(
                    self._ctx.expert_name, "action",
                    f"Initial sync: {pr_count} PR(s), {issue_count} issue(s) saved as records",
                )
            self._synced_at = cycle_started_at
            return None

        # Incremental sync: buffer updated items, process one at a time.
        prs = self._connect.list_prs_since(self._synced_at)
        issues = self._connect.list_issues_since(self._synced_at)
        self._pending.extend(("pr", pr) for pr in prs)
        self._pending.extend(("issue", issue) for issue in issues)
        self._synced_at = cycle_started_at
        return self._pending.pop(0) if self._pending else None

    def _handle(self, item) -> None:
        kind, payload = item
        if kind == "pr":
            rid = self._connect.ingest_pr(payload)
            if rid:
                self._ctx.log.write(
                    self._ctx.expert_name, "action",
                    f"Ingested PR #{payload.get('number', '')} as {rid}",
                )
        elif kind == "issue":
            rid = self._connect.ingest_issue(payload)
            if rid:
                self._ctx.log.write(
                    self._ctx.expert_name, "action",
                    f"Ingested issue #{payload.get('number', '')} as {rid}",
                )


def start(ctx: "ExpertContext"):
    """Entry point called by the expert registry. Returns the polling thread."""
    consumer = GithubIngest(ctx)
    consumer.start()
    ctx.log.write(
        ctx.expert_name, "action",
        f"GitHub ingestion started (interval={int(consumer._poll_interval)}s)",
    )
    return consumer._thread
