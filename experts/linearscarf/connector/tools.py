"""Linear tools exposed to the LLM agent.

These BaseTool subclasses are the surface the linear expert agent uses
to read, search, create, update, and comment on Linear issues. They
wrap LinearClient operations and the Writer's write-back methods.

PearScarf does not auto-discover these yet — that is the registry's job
in a follow-up. For now they are defined and importable, ready to be
wired up once the registry can introspect a connector for its tools.
"""

from __future__ import annotations

from typing import Any

from pearscarf.config import LINEAR_TEAM_ID
from pearscarf.storage import store
from pearscarf.tools import BaseTool

from linearscarf.connector.api_client import LinearClient
from linearscarf.connector.writer import LinearWriter


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

    _PRIORITY_MAP = {"urgent": 1, "high": 2, "medium": 3, "low": 4, "no priority": 0}

    def __init__(self, client: LinearClient) -> None:
        self._client = client

    def execute(self, **kwargs: Any) -> str:
        priority = kwargs.get("priority")
        priority_num = self._PRIORITY_MAP.get(priority.lower()) if priority else None
        team_id = LINEAR_TEAM_ID or None
        if team_id and not (len(team_id) == 36 and "-" in team_id):
            team_id = self._client.resolve_team_id(team_id)

        issues = self._client.list_issues(
            team_id=team_id,
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

    def __init__(self, writer: LinearWriter) -> None:
        self._writer = writer

    def execute(self, **kwargs: Any) -> str:
        result = self._writer.create_issue(
            title=kwargs["title"],
            description=kwargs.get("description", ""),
            team=kwargs.get("team"),
            assignee=kwargs.get("assignee"),
            priority=kwargs.get("priority"),
            project=kwargs.get("project"),
            labels=kwargs.get("labels"),
        )
        if result["ok"]:
            return f"Created: {result.get('identifier', '')} ({result.get('url', '')})"
        return f"Create failed: {result['reason']}"


class LinearUpdateIssueTool(BaseTool):
    name = "linear_update_issue"
    description = "Update an existing Linear issue's status."
    input_schema = {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "Issue identifier, e.g. 'ENG-42'"},
            "status": {"type": "string", "description": "New status name"},
        },
        "required": ["identifier", "status"],
    }

    def __init__(self, client: LinearClient, writer: LinearWriter) -> None:
        self._client = client
        self._writer = writer

    def execute(self, **kwargs: Any) -> str:
        issue = self._client.get_issue(kwargs["identifier"])
        if not issue:
            return f"Issue {kwargs['identifier']} not found."
        result = self._writer.update_status(issue["id"], kwargs["status"])
        if result["ok"]:
            return f"Updated {kwargs['identifier']} → {kwargs['status']}"
        return f"Update failed: {result['reason']}"


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

    def __init__(self, client: LinearClient, writer: LinearWriter) -> None:
        self._client = client
        self._writer = writer

    def execute(self, **kwargs: Any) -> str:
        issue = self._client.get_issue(kwargs["identifier"])
        if not issue:
            return f"Issue {kwargs['identifier']} not found."
        result = self._writer.add_comment(issue["id"], kwargs["body"])
        if result["ok"]:
            return f"Comment added to {kwargs['identifier']} by {result.get('comment_author', 'you')}."
        return f"Comment failed: {result['reason']}"


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


def build_tools(client: LinearClient, writer: LinearWriter) -> list[BaseTool]:
    """Build the full set of Linear tools for the LLM agent.

    Called by the registry once it can wire an expert agent to its tools.
    """
    return [
        LinearListIssuesTool(client),
        LinearGetIssueTool(client),
        LinearSearchIssuesTool(client),
        LinearCreateIssueTool(writer),
        LinearUpdateIssueTool(client, writer),
        LinearAddCommentTool(client, writer),
        SaveIssueTool(),
    ]
