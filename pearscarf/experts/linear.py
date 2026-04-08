"""Linear expert agent — manages issues via Linear's GraphQL API.

The worker delegates Linear tasks here. Tools cover listing, creating,
updating, searching issues, and adding comments.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from pearscarf import log
from pearscarf.agents.expert import ExpertAgent
from pearscarf.bus import MessageBus
from pearscarf.config import LINEAR_API_KEY, LINEAR_POLL_INTERVAL, LINEAR_TEAM_ID
from pearscarf.experts.linear_client import LinearClient
from pearscarf.knowledge import load as load_prompt
from pearscarf.tools import BaseTool, ToolRegistry


_resolved_team_id: str | None = None


def _get_team_id(client: LinearClient) -> str | None:
    """Resolve LINEAR_TEAM_ID (name, key, or UUID) to a UUID. Cached."""
    global _resolved_team_id
    if _resolved_team_id is not None:
        return _resolved_team_id
    if not LINEAR_TEAM_ID:
        return None
    # If it looks like a UUID, use directly
    if len(LINEAR_TEAM_ID) == 36 and "-" in LINEAR_TEAM_ID:
        _resolved_team_id = LINEAR_TEAM_ID
    else:
        _resolved_team_id = client.resolve_team_id(LINEAR_TEAM_ID) or ""
    return _resolved_team_id or None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class LinearListIssuesTool(BaseTool):
    name = "linear_list_issues"
    description = (
        "List issues from Linear. Filter by status, assignee, project, priority, or label."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter by status name (e.g. 'In Progress', 'Done')"},
            "assignee": {"type": "string", "description": "Filter by assignee name"},
            "project": {"type": "string", "description": "Filter by project name"},
            "priority": {"type": "string", "description": "Filter by priority label (e.g. 'Urgent', 'High')"},
            "label": {"type": "string", "description": "Filter by label name"},
        },
    }

    def __init__(self, client: LinearClient) -> None:
        self._client = client

    def execute(self, **kwargs: Any) -> str:
        priority_map = {"urgent": 1, "high": 2, "medium": 3, "low": 4, "no priority": 0}
        priority = kwargs.get("priority")
        priority_num = priority_map.get(priority.lower()) if priority else None

        issues = self._client.list_issues(
            team_id=_get_team_id(self._client),
            status=kwargs.get("status"),
            assignee=kwargs.get("assignee"),
            project=kwargs.get("project"),
            priority=priority_num,
            label=kwargs.get("label"),
        )
        if not issues:
            return "No issues found."
        return _format_issue_list(issues)


class LinearGetIssueTool(BaseTool):
    name = "linear_get_issue"
    description = "Get a specific Linear issue by identifier (e.g. 'ENG-42') with full details and comments."
    input_schema = {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "Issue identifier, e.g. 'ENG-42'"},
        },
        "required": ["identifier"],
    }

    def __init__(self, client: LinearClient) -> None:
        self._client = client

    def execute(self, **kwargs: Any) -> str:
        issue = self._client.get_issue(kwargs["identifier"])
        if not issue:
            return f"Issue {kwargs['identifier']} not found."
        lines = [_format_issue_detail(issue)]
        if issue.get("description"):
            lines.append(f"\nDescription:\n{issue['description'][:1000]}")
        comments = issue.get("comments", [])
        if comments:
            lines.append(f"\nComments ({len(comments)}):")
            for c in comments[:10]:
                lines.append(f"  [{c['author']}] {c['body'][:200]}")
        return "\n".join(lines)


class LinearCreateIssueTool(BaseTool):
    name = "linear_create_issue"
    description = "Create a new issue in Linear."
    input_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Issue title"},
            "description": {"type": "string", "description": "Issue description (markdown)"},
            "team": {"type": "string", "description": "Team name or key (e.g. 'Engineering' or 'ENG')"},
            "assignee": {"type": "string", "description": "Assignee name"},
            "priority": {"type": "string", "description": "Priority: 'Urgent', 'High', 'Medium', 'Low'"},
            "project": {"type": "string", "description": "Project name"},
            "labels": {"type": "array", "items": {"type": "string"}, "description": "Label names"},
        },
        "required": ["title"],
    }

    def __init__(self, client: LinearClient) -> None:
        self._client = client

    def execute(self, **kwargs: Any) -> str:
        # Resolve team
        team_name = kwargs.get("team", "")
        team_id = self._client.resolve_team_id(team_name) if team_name else LINEAR_TEAM_ID
        if not team_id:
            teams = self._client.list_teams()
            if len(teams) == 1:
                team_id = teams[0]["id"]
            else:
                team_names = ", ".join(t["name"] for t in teams)
                return f"Team not found. Available teams: {team_names}"

        # Resolve assignee
        assignee_id = None
        if kwargs.get("assignee"):
            assignee_id = self._client.resolve_user_id(kwargs["assignee"])

        # Resolve priority
        priority_map = {"urgent": 1, "high": 2, "medium": 3, "low": 4}
        priority = kwargs.get("priority")
        priority_num = priority_map.get(priority.lower()) if priority else None

        # Resolve project
        project_id = None
        if kwargs.get("project"):
            project_id = self._client.resolve_project_id(kwargs["project"], team_id)

        # Resolve labels
        label_ids = None
        if kwargs.get("labels"):
            label_ids = self._client.resolve_label_ids(kwargs["labels"], team_id)

        issue = self._client.create_issue(
            title=kwargs["title"],
            team_id=team_id,
            description=kwargs.get("description"),
            assignee_id=assignee_id,
            priority=priority_num,
            project_id=project_id,
            label_ids=label_ids,
        )
        return f"Created: {_format_issue_detail(issue)}"


class LinearUpdateIssueTool(BaseTool):
    name = "linear_update_issue"
    description = "Update an existing Linear issue (change status, priority, assignee, etc.)."
    input_schema = {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "Issue identifier, e.g. 'ENG-42'"},
            "title": {"type": "string", "description": "New title"},
            "status": {"type": "string", "description": "New status name"},
            "priority": {"type": "string", "description": "New priority: 'Urgent', 'High', 'Medium', 'Low'"},
            "assignee": {"type": "string", "description": "New assignee name"},
            "labels": {"type": "array", "items": {"type": "string"}, "description": "New label names"},
        },
        "required": ["identifier"],
    }

    def __init__(self, client: LinearClient) -> None:
        self._client = client

    def execute(self, **kwargs: Any) -> str:
        # Get the issue to find its ID
        issue = self._client.get_issue(kwargs["identifier"])
        if not issue:
            return f"Issue {kwargs['identifier']} not found."

        issue_id = issue["id"]

        # Resolve status to state ID if provided
        state_id = None
        if kwargs.get("status"):
            # Query workflow states to find the state ID
            data = self._client._query("""
                query {
                    workflowStates {
                        nodes { id name }
                    }
                }
            """)
            states = data.get("workflowStates", {}).get("nodes", [])
            for s in states:
                if s["name"].lower() == kwargs["status"].lower():
                    state_id = s["id"]
                    break

        # Resolve other fields
        assignee_id = None
        if kwargs.get("assignee"):
            assignee_id = self._client.resolve_user_id(kwargs["assignee"])

        priority_map = {"urgent": 1, "high": 2, "medium": 3, "low": 4}
        priority = kwargs.get("priority")
        priority_num = priority_map.get(priority.lower()) if priority else None

        label_ids = None
        if kwargs.get("labels"):
            label_ids = self._client.resolve_label_ids(kwargs["labels"])

        updated = self._client.update_issue(
            issue_id=issue_id,
            title=kwargs.get("title"),
            state_id=state_id,
            priority=priority_num,
            assignee_id=assignee_id,
            label_ids=label_ids,
        )
        return f"Updated: {_format_issue_detail(updated)}"


class LinearAddCommentTool(BaseTool):
    name = "linear_add_comment"
    description = "Add a comment to a Linear issue."
    input_schema = {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "Issue identifier, e.g. 'ENG-42'"},
            "body": {"type": "string", "description": "Comment text (markdown)"},
        },
        "required": ["identifier", "body"],
    }

    def __init__(self, client: LinearClient) -> None:
        self._client = client

    def execute(self, **kwargs: Any) -> str:
        issue = self._client.get_issue(kwargs["identifier"])
        if not issue:
            return f"Issue {kwargs['identifier']} not found."
        comment = self._client.add_comment(issue["id"], kwargs["body"])
        return f"Comment added to {kwargs['identifier']} by {comment.get('author', 'you')}."


class LinearSearchIssuesTool(BaseTool):
    name = "linear_search_issues"
    description = "Search Linear issues by text query."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query text"},
        },
        "required": ["query"],
    }

    def __init__(self, client: LinearClient) -> None:
        self._client = client

    def execute(self, **kwargs: Any) -> str:
        issues = self._client.search_issues(kwargs["query"])
        if not issues:
            return "No issues found."
        return _format_issue_list(issues)


class SaveIssueTool(BaseTool):
    name = "save_issue"
    description = (
        "Save an issue to the system of record. Use after reading an issue "
        "to persist it for future reference and indexing."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "linear_id": {"type": "string", "description": "Linear's unique issue ID"},
            "identifier": {"type": "string", "description": "Human-readable ID, e.g. 'ENG-42'"},
            "title": {"type": "string", "description": "Issue title"},
            "description": {"type": "string", "description": "Issue description"},
            "status": {"type": "string", "description": "Issue status"},
            "priority": {"type": "string", "description": "Issue priority"},
            "assignee": {"type": "string", "description": "Assignee name"},
            "project": {"type": "string", "description": "Project name"},
            "labels": {"type": "array", "items": {"type": "string"}, "description": "Label names"},
            "comments": {"type": "array", "items": {"type": "object"}, "description": "Issue comments"},
            "url": {"type": "string", "description": "Issue URL"},
        },
        "required": ["linear_id", "title"],
    }

    def execute(self, **kwargs: Any) -> str:
        from pearscarf.storage import store

        record_id, is_new = store.save_issue(
            source="linear_expert",
            linear_id=kwargs["linear_id"],
            identifier=kwargs.get("identifier", ""),
            title=kwargs["title"],
            description=kwargs.get("description", ""),
            status=kwargs.get("status", ""),
            priority=kwargs.get("priority", ""),
            assignee=kwargs.get("assignee", ""),
            project=kwargs.get("project", ""),
            labels=kwargs.get("labels"),
            comments=kwargs.get("comments"),
            url=kwargs.get("url", ""),
        )
        if is_new:
            return f"Issue saved as {record_id}."
        return f"Issue updated (existing record: {record_id})."


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_issue_list(issues: list[dict]) -> str:
    lines = []
    for i in issues:
        assignee = f" @{i['assignee']}" if i.get("assignee") else ""
        priority = f" [{i['priority']}]" if i.get("priority") else ""
        status = f" ({i['status']})" if i.get("status") else ""
        lines.append(f"- {i['identifier']}: {i['title']}{status}{priority}{assignee}")
    return "\n".join(lines)


def _format_issue_detail(issue: dict) -> str:
    parts = [f"{issue['identifier']}: {issue['title']}"]
    if issue.get("status"):
        parts.append(f"Status: {issue['status']}")
    if issue.get("priority"):
        parts.append(f"Priority: {issue['priority']}")
    if issue.get("assignee"):
        parts.append(f"Assignee: {issue['assignee']}")
    if issue.get("project"):
        parts.append(f"Project: {issue['project']}")
    if issue.get("labels"):
        parts.append(f"Labels: {', '.join(issue['labels'])}")
    if issue.get("url"):
        parts.append(f"URL: {issue['url']}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _create_linear_client() -> LinearClient | None:
    """Create a LinearClient if API key is configured."""
    if not LINEAR_API_KEY:
        return None
    return LinearClient(LINEAR_API_KEY)


def create_linear_expert_for_runner(
    bus: MessageBus | None = None,
) -> tuple[callable | None, LinearClient | None]:
    """Create a factory function for the AgentRunner.

    Returns (agent_factory, client_or_none).
    Returns (None, None) if LINEAR_API_KEY is not set.
    """
    client = _create_linear_client()
    if not client:
        return None, None

    def factory(session_id: str) -> ExpertAgent:
        registry = ToolRegistry()
        registry.register(LinearListIssuesTool(client))
        registry.register(LinearGetIssueTool(client))
        registry.register(LinearCreateIssueTool(client))
        registry.register(LinearUpdateIssueTool(client))
        registry.register(LinearAddCommentTool(client))
        registry.register(LinearSearchIssuesTool(client))
        registry.register(SaveIssueTool())

        return ExpertAgent(
            domain="linear",
            domain_prompt=load_prompt("linear"),
            tool_registry=registry,
            bus=bus,
            agent_name="linear_expert",
        )

    return factory, client


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


def _sync_issue_changes(
    client: LinearClient,
    issue: dict,
    issue_record_id: str,
    since: str | None,
) -> int:
    """Fetch and save history changes for an issue. Returns count of new changes saved."""
    from pearscarf.storage import store

    changes = client.get_issue_history(issue["id"], since=since)
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


def _save_issue_from_poll(issue: dict) -> tuple[str, bool]:
    """Save a polled issue to the SOR. Returns (record_id, is_new)."""
    from pearscarf.storage import store

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


def start_issue_polling(
    bus: MessageBus,
    client: LinearClient,
    interval: int | None = None,
) -> threading.Thread:
    """Start a background daemon thread that polls Linear for new/updated issues.

    First run does a bulk load with batch triage (one session for all issues).
    Subsequent runs create individual sessions for new issues.
    Returns the thread (already started).
    """
    if interval is None:
        interval = LINEAR_POLL_INTERVAL

    team_id = _get_team_id(client)
    if LINEAR_TEAM_ID and not team_id:
        log.write("linear_expert", "--", "error",
                  f"Could not resolve LINEAR_TEAM_ID '{LINEAR_TEAM_ID}' to a team UUID")

    def _poll_loop() -> None:
        synced_at: str | None = None

        while True:
            try:
                if synced_at is None:
                    # Initial load: fetch all issues (paginated)
                    issues = client.list_issues(team_id=team_id)
                    new_records: list[tuple[str, dict]] = []
                    for issue in issues:
                        record_id, is_new = _save_issue_from_poll(issue)
                        if is_new:
                            new_records.append((record_id, issue))

                    if new_records:
                        # Batch triage: one session for all initial issues
                        session_id = bus.create_session(
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
                        bus.send(
                            session_id=session_id,
                            from_agent="linear_expert",
                            to_agent="worker",
                            content="\n".join(lines),
                        )
                        log.write(
                            "linear_expert", session_id, "action",
                            f"Initial sync: {len(new_records)} new issues sent for batch triage",
                        )
                else:
                    # Incremental: one session per new issue + fetch changes
                    issues = client.list_updated_since(synced_at, team_id=team_id)
                    for issue in issues:
                        record_id, is_new = _save_issue_from_poll(issue)

                        # Fetch history changes for updated issues
                        try:
                            n_changes = _sync_issue_changes(
                                client, issue, record_id, since=synced_at,
                            )
                            if n_changes:
                                log.write(
                                    "linear_expert", "--", "action",
                                    f"Poll: {n_changes} change(s) for "
                                    f"{issue.get('identifier', '')}",
                                )
                        except Exception as exc:
                            log.write(
                                "linear_expert", "--", "error",
                                f"History fetch failed for "
                                f"{issue.get('identifier', '')}: {exc}",
                            )

                        if is_new:
                            session_id = bus.create_session(
                                "linear_expert",
                                f"New issue {issue.get('identifier', '')}: {issue.get('title', '')}",
                            )
                            bus.send(
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

                synced_at = datetime.now(timezone.utc).isoformat()

            except Exception as exc:
                log.write("linear_expert", "--", "error", f"Issue poll failed: {exc}")
                try:
                    err_session = bus.create_session("linear_expert", "Poll error")
                    bus.send(
                        session_id=err_session,
                        from_agent="worker",
                        to_agent="human",
                        content=f"Linear poll failed: {exc}",
                    )
                except Exception:
                    pass

            time.sleep(interval)

    thread = threading.Thread(target=_poll_loop, daemon=True, name="linear-poller")
    thread.start()
    return thread
