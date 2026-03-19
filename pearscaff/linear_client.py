"""Linear GraphQL API client.

Thin wrapper around Linear's API for issue management.
"""

from __future__ import annotations

import time

import httpx

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


class LinearClient:
    """Client for Linear's GraphQL API."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._url = "https://api.linear.app/graphql"
        self._teams_cache: list[dict] | None = None
        self._users_cache: list[dict] | None = None

    def _query(self, query: str, variables: dict | None = None) -> dict:
        """Execute a GraphQL query and return the data. Retries on 429."""
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

    # --- Issues ---

    def _paginate_issues(
        self,
        query_template: str,
        variables: dict | None = None,
        page_size: int = 50,
    ) -> list[dict]:
        """Fetch all pages of an issues query. Returns flat list of formatted issues."""
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
        self,
        team_id: str | None = None,
        status: str | None = None,
        assignee: str | None = None,
        project: str | None = None,
        priority: int | None = None,
        label: str | None = None,
        first: int = 50,
    ) -> list[dict]:
        """List issues with optional filters. Paginates through all results."""
        filter_parts: dict = {}
        if team_id:
            filter_parts["team"] = {"id": {"eq": team_id}}
        if status:
            filter_parts["state"] = {"name": {"eqCaseInsensitive": status}}
        if assignee:
            filter_parts["assignee"] = {"name": {"eqCaseInsensitive": assignee}}
        if project:
            filter_parts["project"] = {"name": {"eqCaseInsensitive": project}}
        if priority is not None:
            filter_parts["priority"] = {"eq": priority}
        if label:
            filter_parts["labels"] = {"name": {"eqCaseInsensitive": label}}

        query = """
            query($filter: IssueFilter, $first: Int, $after: String) {
                issues(filter: $filter, first: $first, after: $after, orderBy: updatedAt) {
                    nodes {""" + _ISSUE_FIELDS_WITH_COMMENTS + """}
                    pageInfo { hasNextPage endCursor }
                }
            }
        """
        return self._paginate_issues(
            query, variables={"filter": filter_parts or None}, page_size=first,
        )

    def get_issue(self, identifier: str) -> dict | None:
        """Get a specific issue by identifier (e.g. 'ENG-42')."""
        data = self._query("""
            query($filter: IssueFilter) {
                issues(filter: $filter, first: 1) {
                    nodes {""" + _ISSUE_FIELDS_WITH_COMMENTS + """}
                }
            }
        """, variables={
            "filter": {"identifier": {"eq": identifier}},
        })
        nodes = data.get("issues", {}).get("nodes", [])
        if not nodes:
            return None
        issue = self._format_issue(nodes[0])
        comments = nodes[0].get("comments", {}).get("nodes", [])
        issue["comments"] = [
            {
                "body": c.get("body", ""),
                "author": (c.get("user") or {}).get("name", ""),
                "created_at": c.get("createdAt", ""),
            }
            for c in comments
        ]
        return issue

    def create_issue(
        self,
        title: str,
        team_id: str,
        description: str | None = None,
        assignee_id: str | None = None,
        priority: int | None = None,
        project_id: str | None = None,
        label_ids: list[str] | None = None,
    ) -> dict:
        """Create a new issue."""
        input_fields = f'title: "{title}", teamId: "{team_id}"'
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
                    issue {{
                        id
                        identifier
                        title
                        state {{ name }}
                        priority
                        priorityLabel
                        assignee {{ name email }}
                        project {{ name }}
                        labels {{ nodes {{ name }} }}
                        url
                        createdAt
                        updatedAt
                    }}
                }}
            }}
        """)
        issue_data = data.get("issueCreate", {}).get("issue")
        if not issue_data:
            raise RuntimeError("Issue creation failed")
        return self._format_issue(issue_data)

    def update_issue(
        self,
        issue_id: str,
        title: str | None = None,
        state_id: str | None = None,
        priority: int | None = None,
        assignee_id: str | None = None,
        label_ids: list[str] | None = None,
    ) -> dict:
        """Update an existing issue."""
        input_fields = []
        if title:
            input_fields.append(f'title: "{title}"')
        if state_id:
            input_fields.append(f'stateId: "{state_id}"')
        if priority is not None:
            input_fields.append(f"priority: {priority}")
        if assignee_id:
            input_fields.append(f'assigneeId: "{assignee_id}"')
        if label_ids:
            ids_str = ", ".join(f'"{lid}"' for lid in label_ids)
            input_fields.append(f"labelIds: [{ids_str}]")

        if not input_fields:
            raise ValueError("No fields to update")

        fields_str = ", ".join(input_fields)
        data = self._query(f"""
            mutation {{
                issueUpdate(id: "{issue_id}", input: {{{fields_str}}}) {{
                    success
                    issue {{
                        id
                        identifier
                        title
                        state {{ name }}
                        priority
                        priorityLabel
                        assignee {{ name email }}
                        project {{ name }}
                        labels {{ nodes {{ name }} }}
                        url
                        createdAt
                        updatedAt
                    }}
                }}
            }}
        """)
        issue_data = data.get("issueUpdate", {}).get("issue")
        if not issue_data:
            raise RuntimeError("Issue update failed")
        return self._format_issue(issue_data)

    def add_comment(self, issue_id: str, body: str) -> dict:
        """Add a comment to an issue."""
        escaped = body.replace('"', '\\"').replace("\n", "\\n")
        data = self._query(f"""
            mutation {{
                commentCreate(input: {{issueId: "{issue_id}", body: "{escaped}"}}) {{
                    success
                    comment {{
                        id
                        body
                        user {{ name }}
                        createdAt
                    }}
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

    def search_issues(self, query: str, first: int = 20) -> list[dict]:
        """Search issues by text."""
        data = self._query("""
            query($query: String!, $first: Int) {
                issueSearch(query: $query, first: $first) {
                    nodes {
                        id
                        identifier
                        title
                        state { name }
                        priority
                        priorityLabel
                        assignee { name email }
                        project { name }
                        labels { nodes { name } }
                        url
                        createdAt
                        updatedAt
                    }
                }
            }
        """, variables={"query": query, "first": first})
        return [self._format_issue(n) for n in data.get("issueSearch", {}).get("nodes", [])]

    def list_updated_since(
        self, since: str, team_id: str | None = None, first: int = 50
    ) -> list[dict]:
        """List issues updated since a given ISO timestamp. Paginates through all results."""
        filter_parts: dict = {"updatedAt": {"gt": since}}
        if team_id:
            filter_parts["team"] = {"id": {"eq": team_id}}

        query = """
            query($filter: IssueFilter, $first: Int, $after: String) {
                issues(filter: $filter, first: $first, after: $after, orderBy: updatedAt) {
                    nodes {""" + _ISSUE_FIELDS_WITH_COMMENTS + """}
                    pageInfo { hasNextPage endCursor }
                }
            }
        """
        return self._paginate_issues(
            query, variables={"filter": filter_parts}, page_size=first,
        )

    # --- Resolution helpers ---

    def list_teams(self) -> list[dict]:
        """List all teams. Cached after first call."""
        if self._teams_cache is not None:
            return self._teams_cache
        data = self._query("""
            query {
                teams {
                    nodes { id name key }
                }
            }
        """)
        self._teams_cache = data.get("teams", {}).get("nodes", [])
        return self._teams_cache

    def list_users(self) -> list[dict]:
        """List all users. Cached after first call."""
        if self._users_cache is not None:
            return self._users_cache
        data = self._query("""
            query {
                users {
                    nodes { id name email active }
                }
            }
        """)
        self._users_cache = [
            u for u in data.get("users", {}).get("nodes", [])
            if u.get("active", True)
        ]
        return self._users_cache

    def list_projects(self, team_id: str | None = None) -> list[dict]:
        """List projects."""
        filter_arg = ""
        if team_id:
            filter_arg = f', filter: {{accessibleTeams: {{id: {{eq: "{team_id}"}}}}}}'
        data = self._query(f"""
            query {{
                projects(first: 100{filter_arg}) {{
                    nodes {{ id name }}
                }}
            }}
        """)
        return data.get("projects", {}).get("nodes", [])

    def list_labels(self, team_id: str | None = None) -> list[dict]:
        """List issue labels."""
        filter_arg = ""
        if team_id:
            filter_arg = f', filter: {{team: {{id: {{eq: "{team_id}"}}}}}}'
        data = self._query(f"""
            query {{
                issueLabels(first: 100{filter_arg}) {{
                    nodes {{ id name }}
                }}
            }}
        """)
        return data.get("issueLabels", {}).get("nodes", [])

    def resolve_team_id(self, name_or_key: str) -> str | None:
        """Resolve a team name or key to its ID."""
        for t in self.list_teams():
            if t["name"].lower() == name_or_key.lower() or t["key"].lower() == name_or_key.lower():
                return t["id"]
        return None

    def resolve_user_id(self, name: str) -> str | None:
        """Resolve a user name to their ID."""
        for u in self.list_users():
            if u["name"].lower() == name.lower():
                return u["id"]
        return None

    def resolve_project_id(self, name: str, team_id: str | None = None) -> str | None:
        """Resolve a project name to its ID."""
        for p in self.list_projects(team_id):
            if p["name"].lower() == name.lower():
                return p["id"]
        return None

    def resolve_label_ids(self, names: list[str], team_id: str | None = None) -> list[str]:
        """Resolve label names to their IDs."""
        labels = self.list_labels(team_id)
        label_map = {l["name"].lower(): l["id"] for l in labels}
        return [label_map[n.lower()] for n in names if n.lower() in label_map]

    # --- Formatting ---

    @staticmethod
    def _format_issue(node: dict) -> dict:
        """Normalize a GraphQL issue node into a flat dict."""
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
