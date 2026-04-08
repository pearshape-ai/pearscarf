"""Linear writer — handles write-back requests received from the bus.

LinearWriter exposes write-back operations the linear expert may be
asked to perform: create_issue, update_status, add_comment. The connector
subscribes to the bus and routes write-back messages here.

Unlike gmailscarf's writer (which is a stub), these are real operations
that hit Linear's GraphQL API. Unsupported operations return a structured
graceful decline ({"ok": false, "supported": false, "reason": "..."}).
The writer never raises on a missing capability — only on actual API
errors, which it wraps in {"ok": false, "supported": true, "reason": ...}.
"""

from __future__ import annotations

from pearscarf.config import LINEAR_TEAM_ID

from linearscarf.connector.api_client import LinearClient


def _decline(action: str, reason: str = "not supported yet") -> dict:
    return {
        "ok": False,
        "supported": False,
        "action": action,
        "reason": reason,
    }


def _ok(action: str, **payload) -> dict:
    return {"ok": True, "supported": True, "action": action, **payload}


def _api_error(action: str, exc: Exception) -> dict:
    return {
        "ok": False,
        "supported": True,
        "action": action,
        "reason": f"Linear API error: {exc}",
    }


class LinearWriter:
    """Handles Linear write-back requests routed from the bus."""

    _PRIORITY_MAP = {"urgent": 1, "high": 2, "medium": 3, "low": 4}

    def __init__(self, client: LinearClient) -> None:
        self._client = client

    def create_issue(
        self,
        title: str,
        description: str = "",
        team: str | None = None,
        assignee: str | None = None,
        priority: str | None = None,
        project: str | None = None,
        labels: list[str] | None = None,
    ) -> dict:
        """Create a Linear issue. Returns id + identifier on success."""
        try:
            team_id = self._resolve_team(team)
            if team_id is None:
                teams = self._client.list_teams()
                names = ", ".join(t["name"] for t in teams)
                return {
                    "ok": False,
                    "supported": True,
                    "action": "create_issue",
                    "reason": f"team not found. Available teams: {names}",
                }

            assignee_id = self._client.resolve_user_id(assignee) if assignee else None
            priority_num = self._PRIORITY_MAP.get(priority.lower()) if priority else None
            project_id = self._client.resolve_project_id(project, team_id) if project else None
            label_ids = self._client.resolve_label_ids(labels, team_id) if labels else None

            issue = self._client.create_issue(
                title=title,
                team_id=team_id,
                description=description or None,
                assignee_id=assignee_id,
                priority=priority_num,
                project_id=project_id,
                label_ids=label_ids,
            )
            return _ok(
                "create_issue",
                issue_id=issue.get("id"),
                identifier=issue.get("identifier"),
                url=issue.get("url"),
            )
        except Exception as exc:
            return _api_error("create_issue", exc)

    def update_status(self, issue_id: str, status: str) -> dict:
        """Set a Linear issue's workflow state by name."""
        try:
            data = self._client._query(
                """
                query {
                    workflowStates {
                        nodes { id name }
                    }
                }
                """
            )
            states = data.get("workflowStates", {}).get("nodes", [])
            state_id = None
            for s in states:
                if s["name"].lower() == status.lower():
                    state_id = s["id"]
                    break
            if state_id is None:
                names = ", ".join(s["name"] for s in states)
                return {
                    "ok": False,
                    "supported": True,
                    "action": "update_status",
                    "reason": f"unknown status '{status}'. Known: {names}",
                }

            updated = self._client.update_issue(issue_id=issue_id, state_id=state_id)
            return _ok(
                "update_status",
                issue_id=issue_id,
                identifier=updated.get("identifier"),
                status=status,
            )
        except Exception as exc:
            return _api_error("update_status", exc)

    def add_comment(self, issue_id: str, body: str) -> dict:
        """Add a comment to a Linear issue."""
        try:
            comment = self._client.add_comment(issue_id, body)
            return _ok(
                "add_comment",
                issue_id=issue_id,
                comment_author=comment.get("author"),
            )
        except Exception as exc:
            return _api_error("add_comment", exc)

    def handle(self, action: str, **kwargs) -> dict:
        """Dispatch a write-back action by name. Returns a graceful decline if unknown."""
        method = getattr(self, action, None)
        if method is None or action.startswith("_"):
            return _decline(action, reason=f"unknown action '{action}'")
        return method(**kwargs)

    def _resolve_team(self, team: str | None) -> str | None:
        """Resolve a team name/key to a UUID. Falls back to LINEAR_TEAM_ID if available."""
        if team:
            resolved = self._client.resolve_team_id(team)
            if resolved:
                return resolved
        if LINEAR_TEAM_ID:
            if len(LINEAR_TEAM_ID) == 36 and "-" in LINEAR_TEAM_ID:
                return LINEAR_TEAM_ID
            return self._client.resolve_team_id(LINEAR_TEAM_ID)
        # Fall back to the only team if there's just one
        teams = self._client.list_teams()
        if len(teams) == 1:
            return teams[0]["id"]
        return None
