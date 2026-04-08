"""Linear poller — fetches new issues and issue changes via the GraphQL API.

The LinearPoller is a daemon-thread loop owned by the connector. On the
first cycle it does a bulk load of issues and pushes them as a single
batch-triage session to the worker. On subsequent cycles it incrementally
fetches updated issues, syncs their history changes, and creates one
session per genuinely new issue.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from pearscarf import log
from pearscarf.bus import MessageBus
from pearscarf.config import LINEAR_POLL_INTERVAL, LINEAR_TEAM_ID
from pearscarf.storage import store

from linearscarf.connector.api_client import LinearClient


class LinearPoller:
    """Polls Linear for new and updated issues, pushing records onto the bus."""

    def __init__(
        self,
        bus: MessageBus,
        client: LinearClient,
        interval: int | None = None,
    ) -> None:
        self._bus = bus
        self._client = client
        self._interval = interval if interval is not None else LINEAR_POLL_INTERVAL
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._team_id = self._resolve_team_id()
        self._synced_at: str | None = None

    def _resolve_team_id(self) -> str | None:
        if not LINEAR_TEAM_ID:
            return None
        if len(LINEAR_TEAM_ID) == 36 and "-" in LINEAR_TEAM_ID:
            return LINEAR_TEAM_ID
        team_id = self._client.resolve_team_id(LINEAR_TEAM_ID)
        if not team_id:
            log.write(
                "linear_expert", "--", "error",
                f"Could not resolve LINEAR_TEAM_ID '{LINEAR_TEAM_ID}' to a team UUID",
            )
        return team_id

    def start(self) -> threading.Thread:
        """Start the poll loop in a daemon thread. Returns the thread."""
        self._thread = threading.Thread(
            target=self.run, daemon=True, name="linearscarf-poller"
        )
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        """Poll loop. Runs until stop() is called."""
        while not self._stop.is_set():
            try:
                if self._synced_at is None:
                    self._initial_sync()
                else:
                    self._incremental_sync()
                self._synced_at = datetime.now(timezone.utc).isoformat()
            except Exception as exc:
                log.write("linear_expert", "--", "error", f"Issue poll failed: {exc}")
                self._notify_error(exc)
            self._stop.wait(self._interval)

    def _initial_sync(self) -> None:
        """Bulk-load all issues and post one batch triage session."""
        issues = self._client.list_issues(team_id=self._team_id)
        new_records: list[tuple[str, dict]] = []
        for issue in issues:
            record_id, is_new = self._save_issue(issue)
            if is_new:
                new_records.append((record_id, issue))

        if not new_records:
            return

        session_id = self._bus.create_session(
            "linear_expert",
            f"Initial Linear sync: {len(new_records)} issues",
        )
        lines = [
            f"Initial Linear sync loaded {len(new_records)} issues.\n",
            "Here's a summary for triage — classify as relevant or noise:\n",
        ]
        for rid, iss in new_records:
            status = iss.get("status", "")
            priority = iss.get("priority", "")
            lines.append(
                f"- {rid} | {iss.get('identifier', '')} — "
                f"{iss.get('title', '')} [{status}, {priority}]"
            )
        self._bus.send(
            session_id=session_id,
            from_agent="linear_expert",
            to_agent="worker",
            content="\n".join(lines),
        )
        log.write(
            "linear_expert", session_id, "action",
            f"Initial sync: {len(new_records)} new issues sent for batch triage",
        )

    def _incremental_sync(self) -> None:
        """Fetch updated issues, sync history changes, post per-issue sessions for new ones."""
        issues = self._client.list_updated_since(self._synced_at, team_id=self._team_id)
        for issue in issues:
            record_id, is_new = self._save_issue(issue)

            try:
                n_changes = self._sync_changes(issue, record_id)
                if n_changes:
                    log.write(
                        "linear_expert", "--", "action",
                        f"Poll: {n_changes} change(s) for {issue.get('identifier', '')}",
                    )
            except Exception as exc:
                log.write(
                    "linear_expert", "--", "error",
                    f"History fetch failed for {issue.get('identifier', '')}: {exc}",
                )

            if is_new:
                session_id = self._bus.create_session(
                    "linear_expert",
                    f"New issue {issue.get('identifier', '')}: {issue.get('title', '')}",
                )
                self._bus.send(
                    session_id=session_id,
                    from_agent="linear_expert",
                    to_agent="worker",
                    content=(
                        f"New Linear issue {issue.get('identifier', '')}\n"
                        f"Title: \"{issue.get('title', '')}\"\n"
                        f"Status: {issue.get('status', '')}\n"
                        f"Priority: {issue.get('priority', '')}\n"
                        f"Record: {record_id}\n\n"
                        f"Is this relevant and why?"
                    ),
                )
                log.write(
                    "linear_expert", session_id, "action",
                    f"Poll: new issue {record_id} — {issue.get('identifier', '')}",
                )

    def _save_issue(self, issue: dict) -> tuple[str, bool]:
        """Save an issue to the SOR. Returns (record_id, is_new)."""
        return store.save_issue(
            source="linear_expert",
            linear_id=issue["id"],
            identifier=issue.get("identifier", ""),
            title=issue.get("title", ""),
            description=issue.get("description", ""),
            status=issue.get("status", ""),
            priority=issue.get("priority", ""),
            assignee=issue.get("assignee", ""),
            project=issue.get("project", ""),
            labels=issue.get("labels"),
            comments=issue.get("comments"),
            url=issue.get("url", ""),
            linear_created_at=issue.get("created_at", ""),
            linear_updated_at=issue.get("updated_at", ""),
        )

    def _sync_changes(self, issue: dict, issue_record_id: str) -> int:
        """Fetch and save history changes for an issue. Returns count saved."""
        changes = self._client.get_issue_history(issue["id"], since=self._synced_at)
        saved = 0
        for change in changes:
            record_id = store.save_issue_change(
                issue_record_id=issue_record_id,
                field=change["field"],
                from_value=change.get("from_value", ""),
                to_value=change.get("to_value", ""),
                linear_history_id=change.get("id"),
                changed_by=change.get("actor", ""),
                changed_at=change.get("created_at", ""),
            )
            if record_id:
                saved += 1
        return saved

    def _notify_error(self, exc: Exception) -> None:
        """Surface a poll error to the human via the bus."""
        try:
            err_session = self._bus.create_session("linear_expert", "Poll error")
            self._bus.send(
                session_id=err_session,
                from_agent="worker",
                to_agent="human",
                content=f"Linear poll failed: {exc}",
            )
        except Exception:
            pass
