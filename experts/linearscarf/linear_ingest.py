"""Linear background ingestion — `LinearIngest` consumer.

Polls Linear for new issues and history changes and saves each as a
record via `ctx.storage.save_record()`. Records land with
`classification=pending_triage`; Triage picks them up via queue
polling. This ingester does not touch the bus.

Polls run in two modes: an initial bulk load (first cycle) and
incremental sync (each subsequent cycle, filtered by `synced_at`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pearscarf.consumer import Consumer

if TYPE_CHECKING:
    from pearscarf.expert_context import ExpertContext


class LinearIngest(Consumer):
    """Consumer that polls Linear and saves issues + history changes as records."""

    name = "linearscarf"
    default_poll_interval = 300.0

    def __init__(self, ctx: "ExpertContext", poll_interval: float | None = None) -> None:
        from linearscarf.linear_connect import LinearConnect

        if poll_interval is None:
            poll_interval = float(ctx.config.get("LINEAR_POLL_INTERVAL", self.default_poll_interval))
        super().__init__(poll_interval=poll_interval)

        self._ctx = ctx
        self._connect = LinearConnect(ctx)
        self._synced_at: str | None = None
        self._pending: list = []  # list of issue dicts to process

    def _next(self):
        if self._pending:
            return self._pending.pop(0)

        # No buffered work — run the next sync cycle.
        cycle_started_at = datetime.now(timezone.utc).isoformat()
        try:
            if self._synced_at is None:
                issues = self._connect.list_issues()
                initial = True
            else:
                issues = self._connect.list_updated_since(self._synced_at)
                initial = False
        except Exception:
            # Let base-class error handling take over in _next.
            raise

        if initial and issues:
            saved = 0
            for issue in issues:
                rid = self._connect.ingest_record(issue)
                if rid:
                    saved += 1
            if saved:
                self._ctx.log.write(
                    self._ctx.expert_name, "action",
                    f"Initial sync: {saved} new issues saved as records",
                )
            # Initial sync processed inline — no per-item _handle pass needed.
            self._synced_at = cycle_started_at
            return None

        if not initial:
            self._pending = list(issues)
        self._synced_at = cycle_started_at
        return self._pending.pop(0) if self._pending else None

    def _handle(self, issue) -> None:
        """Incremental-cycle per-issue work: ingest + history sync."""
        rid = self._connect.ingest_record(issue)
        is_new = rid is not None

        # Sync history changes for this issue, using the previous cycle's
        # synced_at as the lower bound (captured before this cycle ran).
        try:
            changes = self._connect.get_issue_history(issue["id"], since=self._synced_at)
            issue_record_id = rid or f"issue_{issue.get('identifier', 'unknown')}"
            saved = 0
            for change in changes:
                crid = self._connect.ingest_change(change, issue_record_id)
                if crid:
                    saved += 1
            if saved:
                self._ctx.log.write(
                    self._ctx.expert_name, "action",
                    f"Poll: {saved} change(s) for {issue.get('identifier', '')}",
                )
        except Exception as exc:
            self._ctx.log.write(
                self._ctx.expert_name, "error",
                f"History fetch failed for {issue.get('identifier', '')}: {exc}",
            )

        if is_new:
            self._ctx.log.write(
                self._ctx.expert_name, "action",
                f"Ingested {rid}: {issue.get('identifier', '')} — {issue.get('title', '')}",
            )


def start(ctx: "ExpertContext"):
    """Entry point called by the expert registry. Returns the polling thread."""
    consumer = LinearIngest(ctx)
    consumer.start()
    ctx.log.write(
        ctx.expert_name, "action",
        f"Linear ingestion started (interval={int(consumer._poll_interval)}s)",
    )
    return consumer._thread
