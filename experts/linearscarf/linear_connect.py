"""Linear API client + tool definitions.

Provides LinearConnect (GraphQL client, tools, ingest_record) and the
module-level get_tools(ctx) entry point called by pearscarf at startup.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

import httpx

from pearscarf.tools import BaseTool

if TYPE_CHECKING:
    from pearscarf.expert_context import ExpertContext


# --- GraphQL field fragments ---

_ISSUE_FIELDS = """
    id identifier title description
    state { name }
    priority priorityLabel
    assignee { name email }
    project { name }
    labels { nodes { name } }
    url createdAt updatedAt
"""

_ISSUE_FIELDS_WITH_COMMENTS = _ISSUE_FIELDS + """
    comments { nodes { body user { name } createdAt } }
"""


# --- LinearConnect ---


class LinearConnect:
    """Authenticated Linear client + tool factory.

    Shared by both the LLM agent (via get_tools) and the ingester
    (via ingest_record). One API client, no duplication.
    """

    def __init__(self, ctx: ExpertContext) -> None:
        self._ctx = ctx
        self._api_key = ctx.config.get("LINEAR_API_KEY", "")
        self._team_id_raw = ctx.config.get("LINEAR_TEAM_ID", "")
        self._url = "https://api.linear.app/graphql"
        self._teams_cache: list[dict] | None = None
        self._users_cache: list[dict] | None = None
        self._team_id: str | None = None

    def _ensure_team_id(self) -> str | None:
        if self._team_id is not None:
            return self._team_id
        raw = self._team_id_raw
        if not raw:
            return None
        if len(raw) == 36 and "-" in raw:
            self._team_id = raw
        else:
            self._team_id = self.resolve_team_id(raw)
        return self._team_id

    # --- GraphQL transport ---

    def _query(self, query: str, variables: dict | None = None) -> dict:
        max_retries = 3
        for attempt in range(max_retries + 1):
            resp = httpx.post(
                self._url,
                json={"query": query, "variables": variables or {}},
                headers={
                    "Authorization": self._api_key,
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            if resp.status_code == 429:
                if attempt < max_retries:
                    retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
                    time.sleep(retry_after)
                    continue
            resp.raise_for_status()
            result = resp.json()
            if "errors" in result:
                raise RuntimeError(f"Linear API error: {result['errors']}")
            return result.get("data", {})
        raise RuntimeError("Linear API rate limit exceeded after retries")

    # --- Issue queries ---

    def _paginate_issues(
        self, query_template: str, variables: dict | None = None, page_size: int = 50
    ) -> list[dict]:
        all_issues: list[dict] = []
        cursor: str | None = None
        while True:
            vars_ = dict(variables or {})
            vars_["first"] = page_size
            if cursor:
                vars_["after"] = cursor

            data = self._query(query_template, variables=vars_)
            issues_data = data.get("issues", {})
            nodes = issues_data.get("nodes", [])
            page_info = issues_data.get("pageInfo", {})

            for node in nodes:
                issue = self._format_issue(node)
                comments_raw = node.get("comments", {}).get("nodes", [])
                if comments_raw:
                    issue["comments"] = [
                        {
                            "body": c.get("body", ""),
                            "author": (c.get("user") or {}).get("name", ""),
                            "created_at": c.get("createdAt", ""),
                        }
                        for c in comments_raw
                    ]
                all_issues.append(issue)

            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            if not cursor:
                break

        return all_issues

    def list_issues(
        self, team_id: str | None = None, status: str | None = None,
        assignee: str | None = None, project: str | None = None,
        priority: int | None = None, label: str | None = None, first: int = 50,
    ) -> list[dict]:
        filter_parts: dict = {}
        tid = team_id or self._ensure_team_id()
        if tid:
            filter_parts["team"] = {"id": {"eq": tid}}
        if status:
            filter_parts["state"] = {"name": {"eq": status}}
        if assignee:
            filter_parts["assignee"] = {"name": {"eq": assignee}}
        if project:
            filter_parts["project"] = {"name": {"eq": project}}
        if priority is not None:
            filter_parts["priority"] = {"eq": priority}
        if label:
            filter_parts["labels"] = {"name": {"eq": label}}

        query = """
            query($filter: IssueFilter, $first: Int, $after: String) {
                issues(filter: $filter, first: $first, after: $after, orderBy: updatedAt) {
                    nodes {""" + _ISSUE_FIELDS_WITH_COMMENTS + """}
                    pageInfo { hasNextPage endCursor }
                }
            }
        """
        return self._paginate_issues(query, variables={"filter": filter_parts or None}, page_size=first)

    def get_issue(self, identifier: str) -> dict | None:
        """Get a specific issue by identifier (e.g. 'PEA-88').

        Parses the identifier into team key + number for the filter.
        """
        # Parse "PEA-88" → key="PEA", number=88
        parts = identifier.rsplit("-", 1)
        if len(parts) != 2 or not parts[1].isdigit():
            return None
        team_key, number = parts[0], int(parts[1])

        data = self._query("""
            query($filter: IssueFilter) {
                issues(filter: $filter, first: 1) {
                    nodes {""" + _ISSUE_FIELDS_WITH_COMMENTS + """}
                }
            }
        """, variables={"filter": {"number": {"eq": number}, "team": {"key": {"eq": team_key}}}})
        nodes = data.get("issues", {}).get("nodes", [])
        if not nodes:
            return None
        issue = self._format_issue(nodes[0])
        comments = nodes[0].get("comments", {}).get("nodes", [])
        issue["comments"] = [
            {"body": c.get("body", ""), "author": (c.get("user") or {}).get("name", ""), "created_at": c.get("createdAt", "")}
            for c in comments
        ]
        return issue

    def search_issues(self, term: str, first: int = 20) -> list[dict]:
        data = self._query("""
            query($term: String!, $first: Int) {
                searchIssues(term: $term, first: $first) {
                    nodes {""" + _ISSUE_FIELDS + """}
                }
            }
        """, variables={"term": term, "first": first})
        return [self._format_issue(n) for n in data.get("searchIssues", {}).get("nodes", [])]

    def list_updated_since(self, since: str, team_id: str | None = None, first: int = 50) -> list[dict]:
        filter_parts: dict = {"updatedAt": {"gt": since}}
        tid = team_id or self._ensure_team_id()
        if tid:
            filter_parts["team"] = {"id": {"eq": tid}}
        query = """
            query($filter: IssueFilter, $first: Int, $after: String) {
                issues(filter: $filter, first: $first, after: $after, orderBy: updatedAt) {
                    nodes {""" + _ISSUE_FIELDS_WITH_COMMENTS + """}
                    pageInfo { hasNextPage endCursor }
                }
            }
        """
        return self._paginate_issues(query, variables={"filter": filter_parts}, page_size=first)

    # --- Mutations ---

    def create_issue(
        self, title: str, team_id: str | None = None,
        description: str | None = None, assignee_id: str | None = None,
        priority: int | None = None, project_id: str | None = None,
        label_ids: list[str] | None = None,
    ) -> dict:
        tid = team_id or self._ensure_team_id()
        if not tid:
            raise RuntimeError("No team ID — set LINEAR_TEAM_ID")
        input_fields = f'title: "{title}", teamId: "{tid}"'
        if description:
            escaped = description.replace('"', '\\"').replace("\n", "\\n")
            input_fields += f', description: "{escaped}"'
        if assignee_id:
            input_fields += f', assigneeId: "{assignee_id}"'
        if priority is not None:
            input_fields += f", priority: {priority}"
        if project_id:
            input_fields += f', projectId: "{project_id}"'
        if label_ids:
            ids_str = ", ".join(f'"{lid}"' for lid in label_ids)
            input_fields += f", labelIds: [{ids_str}]"

        data = self._query(f"""
            mutation {{
                issueCreate(input: {{{input_fields}}}) {{
                    success
                    issue {{ {_ISSUE_FIELDS} }}
                }}
            }}
        """)
        issue_data = data.get("issueCreate", {}).get("issue")
        if not issue_data:
            raise RuntimeError("Issue creation failed")
        return self._format_issue(issue_data)

    def update_issue_status(self, issue_id: str, state_id: str) -> dict:
        data = self._query(f"""
            mutation {{
                issueUpdate(id: "{issue_id}", input: {{stateId: "{state_id}"}}) {{
                    success
                    issue {{ {_ISSUE_FIELDS} }}
                }}
            }}
        """)
        issue_data = data.get("issueUpdate", {}).get("issue")
        if not issue_data:
            raise RuntimeError("Issue update failed")
        return self._format_issue(issue_data)

    def add_comment(self, issue_id: str, body: str) -> dict:
        escaped = body.replace('"', '\\"').replace("\n", "\\n")
        data = self._query(f"""
            mutation {{
                commentCreate(input: {{issueId: "{issue_id}", body: "{escaped}"}}) {{
                    success
                    comment {{ id body user {{ name }} createdAt }}
                }}
            }}
        """)
        comment = data.get("commentCreate", {}).get("comment", {})
        return {
            "id": comment.get("id", ""),
            "body": comment.get("body", ""),
            "author": (comment.get("user") or {}).get("name", ""),
            "created_at": comment.get("createdAt", ""),
        }

    # --- History ---

    _PRIORITY_LABELS = {0: "No priority", 1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}

    def get_issue_history(self, issue_id: str, since: str | None = None) -> list[dict]:
        all_entries: list[dict] = []
        cursor: str | None = None
        while True:
            vars_: dict = {"issueId": issue_id, "first": 50}
            if cursor:
                vars_["after"] = cursor
            data = self._query("""
                query($issueId: String!, $first: Int, $after: String) {
                    issue(id: $issueId) {
                        history(first: $first, after: $after) {
                            nodes {
                                id createdAt
                                actor { name email }
                                fromState { name } toState { name }
                                fromAssignee { name } toAssignee { name }
                                fromPriority toPriority
                            }
                            pageInfo { hasNextPage endCursor }
                        }
                    }
                }
            """, variables=vars_)

            history = data.get("issue", {}).get("history", {})
            nodes = history.get("nodes", [])
            page_info = history.get("pageInfo", {})

            for node in nodes:
                created_at = node.get("createdAt", "")
                if since and created_at <= since:
                    continue
                actor_name = (node.get("actor") or {}).get("name", "")

                if node.get("fromState") or node.get("toState"):
                    all_entries.append({
                        "id": node["id"], "created_at": created_at, "actor": actor_name,
                        "field": "status",
                        "from_value": (node.get("fromState") or {}).get("name", ""),
                        "to_value": (node.get("toState") or {}).get("name", ""),
                    })
                if node.get("fromAssignee") or node.get("toAssignee"):
                    all_entries.append({
                        "id": node["id"] + "_assignee", "created_at": created_at, "actor": actor_name,
                        "field": "assignee",
                        "from_value": (node.get("fromAssignee") or {}).get("name", ""),
                        "to_value": (node.get("toAssignee") or {}).get("name", ""),
                    })
                from_p, to_p = node.get("fromPriority"), node.get("toPriority")
                if (from_p is not None or to_p is not None) and from_p != to_p:
                    all_entries.append({
                        "id": node["id"] + "_priority", "created_at": created_at, "actor": actor_name,
                        "field": "priority",
                        "from_value": self._PRIORITY_LABELS.get(from_p, str(from_p)) if from_p is not None else "",
                        "to_value": self._PRIORITY_LABELS.get(to_p, str(to_p)) if to_p is not None else "",
                    })

            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            if not cursor:
                break
        return all_entries

    # --- Resolution helpers ---

    def list_teams(self) -> list[dict]:
        if self._teams_cache is not None:
            return self._teams_cache
        data = self._query("query { teams { nodes { id name key } } }")
        self._teams_cache = data.get("teams", {}).get("nodes", [])
        return self._teams_cache

    def list_users(self) -> list[dict]:
        if self._users_cache is not None:
            return self._users_cache
        data = self._query("query { users { nodes { id name email active } } }")
        self._users_cache = [u for u in data.get("users", {}).get("nodes", []) if u.get("active", True)]
        return self._users_cache

    def list_workflow_states(self, team_id: str | None = None) -> list[dict]:
        tid = team_id or self._ensure_team_id()
        filter_arg = f', filter: {{team: {{id: {{eq: "{tid}"}}}}}}' if tid else ""
        data = self._query(f"query {{ workflowStates(first: 100{filter_arg}) {{ nodes {{ id name }} }} }}")
        return data.get("workflowStates", {}).get("nodes", [])

    def list_projects(self, team_id: str | None = None) -> list[dict]:
        tid = team_id or self._ensure_team_id()
        filter_arg = f', filter: {{accessibleTeams: {{id: {{eq: "{tid}"}}}}}}' if tid else ""
        data = self._query(f"query {{ projects(first: 100{filter_arg}) {{ nodes {{ id name }} }} }}")
        return data.get("projects", {}).get("nodes", [])

    def list_labels(self, team_id: str | None = None) -> list[dict]:
        tid = team_id or self._ensure_team_id()
        filter_arg = f', filter: {{team: {{id: {{eq: "{tid}"}}}}}}' if tid else ""
        data = self._query(f"query {{ issueLabels(first: 100{filter_arg}) {{ nodes {{ id name }} }} }}")
        return data.get("issueLabels", {}).get("nodes", [])

    def resolve_team_id(self, name_or_key: str) -> str | None:
        for t in self.list_teams():
            if t["name"].lower() == name_or_key.lower() or t["key"].lower() == name_or_key.lower():
                return t["id"]
        return None

    def resolve_user_id(self, name: str) -> str | None:
        for u in self.list_users():
            if u["name"].lower() == name.lower():
                return u["id"]
        return None

    def resolve_state_id(self, name: str) -> str | None:
        for s in self.list_workflow_states():
            if s["name"].lower() == name.lower():
                return s["id"]
        return None

    def resolve_project_id(self, name: str) -> str | None:
        for p in self.list_projects():
            if p["name"].lower() == name.lower():
                return p["id"]
        return None

    def resolve_label_ids(self, names: list[str]) -> list[str]:
        labels = self.list_labels()
        label_map = {l["name"].lower(): l["id"] for l in labels}
        return [label_map[n.lower()] for n in names if n.lower() in label_map]

    # --- Record ingestion ---

    def ingest_record(self, data: dict) -> str | None:
        """Save an issue record. Returns record_id or None on duplicate."""
        raw = json.dumps(data)
        content = (
            f"Issue: {data.get('identifier', '')} — {data.get('title', '')}\n"
            f"Status: {data.get('status', '')}\n"
            f"Priority: {data.get('priority', '')}\n"
            f"Assignee: {data.get('assignee', '')}\n"
            f"Project: {data.get('project', '')}\n"
            f"URL: {data.get('url', '')}\n"
        )
        description = data.get("description")
        if description:
            content += f"\n{description[:2000]}"
        metadata = {
            "linear_id": data.get("id", ""),
            "identifier": data.get("identifier", ""),
            "title": data.get("title", ""),
            "status": data.get("status", ""),
            "priority": data.get("priority", ""),
            "assignee": data.get("assignee", ""),
            "project": data.get("project", ""),
            "labels": data.get("labels", []),
            "url": data.get("url", ""),
            "linear_created_at": data.get("created_at", ""),
            "linear_updated_at": data.get("updated_at", ""),
        }
        return self._ctx.storage.save_record(
            "linear_issue", raw, content=content, metadata=metadata,
            dedup_key=data.get("id"),
        )

    def ingest_change(self, change: dict, issue_record_id: str) -> str | None:
        """Save an issue change record. Returns record_id or None on duplicate."""
        raw = json.dumps(change)
        content = (
            f"Issue {issue_record_id}: {change.get('field', '')} changed "
            f"from '{change.get('from_value', '')}' to '{change.get('to_value', '')}' "
            f"by {change.get('actor', '')} at {change.get('created_at', '')}"
        )
        metadata = {
            "issue_record_id": issue_record_id,
            "field": change.get("field", ""),
            "from_value": change.get("from_value", ""),
            "to_value": change.get("to_value", ""),
            "changed_by": change.get("actor", ""),
            "changed_at": change.get("created_at", ""),
            "linear_history_id": change.get("id", ""),
        }
        return self._ctx.storage.save_record(
            "linear_issue_change", raw, content=content, metadata=metadata,
            dedup_key=change.get("id"),
        )

    # --- Formatting ---

    @staticmethod
    def _format_issue(node: dict) -> dict:
        return {
            "id": node.get("id", ""),
            "identifier": node.get("identifier", ""),
            "title": node.get("title", ""),
            "description": node.get("description"),
            "status": (node.get("state") or {}).get("name", ""),
            "priority": node.get("priorityLabel", ""),
            "priority_number": node.get("priority"),
            "assignee": (node.get("assignee") or {}).get("name", ""),
            "assignee_email": (node.get("assignee") or {}).get("email", ""),
            "project": (node.get("project") or {}).get("name", ""),
            "labels": [l["name"] for l in (node.get("labels") or {}).get("nodes", [])],
            "url": node.get("url", ""),
            "created_at": node.get("createdAt", ""),
            "updated_at": node.get("updatedAt", ""),
        }

    # --- Tools ---

    def get_tools(self) -> list[BaseTool]:
        return [
            LinearListIssuesTool(self),
            LinearGetIssueTool(self),
            LinearSearchIssuesTool(self),
            LinearCreateIssueTool(self),
            LinearUpdateIssueTool(self),
            LinearAddCommentTool(self),
            SaveIssueTool(self),
        ]


# --- Tool definitions ---


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
    for key in ("status", "priority", "assignee", "project", "url"):
        if issue.get(key):
            parts.append(f"{key.title()}: {issue[key]}")
    if issue.get("labels"):
        parts.append(f"Labels: {', '.join(issue['labels'])}")
    return "\n".join(parts)


class LinearListIssuesTool(BaseTool):
    name = "linear_list_issues"
    description = "List issues from Linear. Filter by status, assignee, project, priority, or label."
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

    def __init__(self, connect: LinearConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        priority = kwargs.get("priority")
        priority_num = self._PRIORITY_MAP.get(priority.lower()) if priority else None
        issues = self._connect.list_issues(
            status=kwargs.get("status"), assignee=kwargs.get("assignee"),
            project=kwargs.get("project"), priority=priority_num, label=kwargs.get("label"),
        )
        if not issues:
            return "No issues found."
        return _format_issue_list(issues)


class LinearGetIssueTool(BaseTool):
    name = "linear_get_issue"
    description = "Get a specific Linear issue by identifier (e.g. 'PEA-42') with full details and comments."
    input_schema = {
        "type": "object",
        "properties": {"identifier": {"type": "string", "description": "Issue identifier, e.g. 'PEA-42'"}},
        "required": ["identifier"],
    }

    def __init__(self, connect: LinearConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        issue = self._connect.get_issue(kwargs["identifier"])
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
        "properties": {"query": {"type": "string", "description": "Search query text"}},
        "required": ["query"],
    }

    def __init__(self, connect: LinearConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        issues = self._connect.search_issues(kwargs["query"])  # "query" from LLM → "term" in API
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
            "assignee": {"type": "string", "description": "Assignee name"},
            "priority": {"type": "string", "description": "Priority: 'Urgent', 'High', 'Medium', 'Low'"},
            "project": {"type": "string", "description": "Project name"},
            "labels": {"type": "array", "items": {"type": "string"}, "description": "Label names"},
        },
        "required": ["title"],
    }
    _PRIORITY_MAP = {"urgent": 1, "high": 2, "medium": 3, "low": 4}

    def __init__(self, connect: LinearConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        c = self._connect
        assignee_id = c.resolve_user_id(kwargs["assignee"]) if kwargs.get("assignee") else None
        priority_num = self._PRIORITY_MAP.get(kwargs.get("priority", "").lower())
        project_id = c.resolve_project_id(kwargs["project"]) if kwargs.get("project") else None
        label_ids = c.resolve_label_ids(kwargs["labels"]) if kwargs.get("labels") else None

        issue = c.create_issue(
            title=kwargs["title"], description=kwargs.get("description"),
            assignee_id=assignee_id, priority=priority_num,
            project_id=project_id, label_ids=label_ids,
        )
        return f"Created: {issue.get('identifier', '')} ({issue.get('url', '')})"


class LinearUpdateIssueTool(BaseTool):
    name = "linear_update_issue"
    description = "Update an existing Linear issue's status."
    input_schema = {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "Issue identifier, e.g. 'PEA-42'"},
            "status": {"type": "string", "description": "New status name"},
        },
        "required": ["identifier", "status"],
    }

    def __init__(self, connect: LinearConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        c = self._connect
        issue = c.get_issue(kwargs["identifier"])
        if not issue:
            return f"Issue {kwargs['identifier']} not found."
        state_id = c.resolve_state_id(kwargs["status"])
        if not state_id:
            return f"Status '{kwargs['status']}' not found."
        c.update_issue_status(issue["id"], state_id)
        return f"Updated {kwargs['identifier']} → {kwargs['status']}"


class LinearAddCommentTool(BaseTool):
    name = "linear_add_comment"
    description = "Add a comment to a Linear issue."
    input_schema = {
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "Issue identifier, e.g. 'PEA-42'"},
            "body": {"type": "string", "description": "Comment text (markdown)"},
        },
        "required": ["identifier", "body"],
    }

    def __init__(self, connect: LinearConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        issue = self._connect.get_issue(kwargs["identifier"])
        if not issue:
            return f"Issue {kwargs['identifier']} not found."
        result = self._connect.add_comment(issue["id"], kwargs["body"])
        return f"Comment added to {kwargs['identifier']}."


class SaveIssueTool(BaseTool):
    name = "save_issue"
    description = "Save an issue to the system of record for future reference and indexing."
    input_schema = {
        "type": "object",
        "properties": {
            "linear_id": {"type": "string", "description": "Linear's unique issue ID"},
            "identifier": {"type": "string", "description": "Human-readable ID, e.g. 'PEA-42'"},
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

    def __init__(self, connect: LinearConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        rid = self._connect.ingest_record(kwargs)
        if rid is None:
            return "Issue already stored (duplicate)."
        return f"Issue saved as {rid}."


# --- Module entry point ---


def get_tools(ctx: ExpertContext) -> LinearConnect:
    """Entry point called by pearscarf at startup."""
    return LinearConnect(ctx)
