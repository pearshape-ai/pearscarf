"""GitHub REST API client + tool definitions.

Provides GitHubConnect (REST client, tools, ingest_record) and the
module-level get_tools(ctx) entry point called by pearscarf at startup.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx

from pearscarf.tools import BaseTool

if TYPE_CHECKING:
    from pearscarf.expert_context import ExpertContext


class GitHubConnect:
    """Authenticated GitHub client + tool factory."""

    def __init__(self, ctx: ExpertContext) -> None:
        self._ctx = ctx
        self._token = ctx.config.get("GITHUB_TOKEN", "")
        self._repo = ctx.config.get("GITHUB_REPO", "")
        self._base = "https://api.github.com"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get(self, path: str, params: dict | None = None) -> Any:
        resp = httpx.get(
            f"{self._base}{path}",
            headers=self._headers(),
            params=params or {},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # --- PRs ---

    def list_prs(self, state: str = "open", per_page: int = 30) -> list[dict]:
        raw = self._get(f"/repos/{self._repo}/pulls", {"state": state, "per_page": per_page})
        return [self._format_pr(p) for p in raw]

    def get_pr(self, number: int) -> dict | None:
        try:
            raw = self._get(f"/repos/{self._repo}/pulls/{number}")
            return self._format_pr(raw)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    # --- Issues ---

    def list_issues(self, state: str = "open", per_page: int = 30) -> list[dict]:
        raw = self._get(f"/repos/{self._repo}/issues", {"state": state, "per_page": per_page})
        # GitHub API returns PRs mixed with issues — filter them out
        return [self._format_issue(i) for i in raw if "pull_request" not in i]

    def get_issue(self, number: int) -> dict | None:
        try:
            raw = self._get(f"/repos/{self._repo}/issues/{number}")
            if "pull_request" in raw:
                return None  # it's a PR, not an issue
            return self._format_issue(raw)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    # --- Polling helpers ---

    def list_prs_since(self, since: str, state: str = "all", per_page: int = 100) -> list[dict]:
        raw = self._get(
            f"/repos/{self._repo}/pulls",
            {"state": state, "sort": "updated", "direction": "desc", "per_page": per_page},
        )
        return [self._format_pr(p) for p in raw if p.get("updated_at", "") > since]

    def list_issues_since(self, since: str, state: str = "all", per_page: int = 100) -> list[dict]:
        raw = self._get(
            f"/repos/{self._repo}/issues",
            {"state": state, "since": since, "per_page": per_page},
        )
        return [self._format_issue(i) for i in raw if "pull_request" not in i]

    # --- Record ingestion ---

    def ingest_pr(self, data: dict) -> str | None:
        raw = json.dumps(data)
        content = (
            f"PR #{data.get('number', '')}: {data.get('title', '')}\n"
            f"Author: {data.get('author', '')}\n"
            f"State: {data.get('state', '')}\n"
            f"Branch: {data.get('branch', '')} → {data.get('base_branch', '')}\n"
            f"URL: {data.get('url', '')}\n"
        )
        body = data.get("body")
        if body:
            content += f"\n{body[:2000]}"
        metadata = {
            "github_id": data.get("github_id", ""),
            "number": data.get("number", ""),
            "title": data.get("title", ""),
            "state": data.get("state", ""),
            "author": data.get("author", ""),
            "branch": data.get("branch", ""),
            "base_branch": data.get("base_branch", ""),
            "labels": data.get("labels", []),
            "reviewers": data.get("reviewers", []),
            "url": data.get("url", ""),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "merged_at": data.get("merged_at", ""),
        }
        return self._ctx.storage.save_record(
            "github_pr", raw, content=content, metadata=metadata,
            dedup_key=str(data.get("github_id", "")),
        )

    def ingest_issue(self, data: dict) -> str | None:
        raw = json.dumps(data)
        content = (
            f"Issue #{data.get('number', '')}: {data.get('title', '')}\n"
            f"Author: {data.get('author', '')}\n"
            f"State: {data.get('state', '')}\n"
            f"URL: {data.get('url', '')}\n"
        )
        body = data.get("body")
        if body:
            content += f"\n{body[:2000]}"
        metadata = {
            "github_id": data.get("github_id", ""),
            "number": data.get("number", ""),
            "title": data.get("title", ""),
            "state": data.get("state", ""),
            "author": data.get("author", ""),
            "assignees": data.get("assignees", []),
            "labels": data.get("labels", []),
            "url": data.get("url", ""),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "closed_at": data.get("closed_at", ""),
        }
        return self._ctx.storage.save_record(
            "github_issue", raw, content=content, metadata=metadata,
            dedup_key=str(data.get("github_id", "")),
        )

    def ingest_record(self, data: dict) -> str | None:
        """Route to ingest_pr or ingest_issue based on data shape."""
        if "branch" in data or "base_branch" in data or "merged_at" in data:
            return self.ingest_pr(data)
        return self.ingest_issue(data)

    # --- Formatting ---

    @staticmethod
    def _format_pr(node: dict) -> dict:
        return {
            "github_id": node.get("id", ""),
            "number": node.get("number", ""),
            "title": node.get("title", ""),
            "body": node.get("body") or "",
            "state": node.get("state", ""),
            "author": (node.get("user") or {}).get("login", ""),
            "branch": (node.get("head") or {}).get("ref", ""),
            "base_branch": (node.get("base") or {}).get("ref", ""),
            "labels": [l["name"] for l in node.get("labels", [])],
            "reviewers": [r["login"] for r in node.get("requested_reviewers", [])],
            "url": node.get("html_url", ""),
            "created_at": node.get("created_at", ""),
            "updated_at": node.get("updated_at", ""),
            "merged_at": node.get("merged_at") or "",
        }

    @staticmethod
    def _format_issue(node: dict) -> dict:
        return {
            "github_id": node.get("id", ""),
            "number": node.get("number", ""),
            "title": node.get("title", ""),
            "body": node.get("body") or "",
            "state": node.get("state", ""),
            "author": (node.get("user") or {}).get("login", ""),
            "assignees": [a["login"] for a in node.get("assignees", [])],
            "labels": [l["name"] for l in node.get("labels", [])],
            "url": node.get("html_url", ""),
            "created_at": node.get("created_at", ""),
            "updated_at": node.get("updated_at", ""),
            "closed_at": node.get("closed_at") or "",
        }

    # --- Tools ---

    def get_tools(self) -> list[BaseTool]:
        return [
            GitHubListPRsTool(self),
            GitHubGetPRTool(self),
            GitHubListIssuesTool(self),
            GitHubGetIssueTool(self),
            SavePRTool(self),
            SaveIssueTool(self),
        ]


# --- Tool definitions ---


def _format_pr_list(prs: list[dict]) -> str:
    lines = []
    for p in prs:
        author = f" @{p['author']}" if p.get("author") else ""
        state = f" ({p['state']})" if p.get("state") else ""
        lines.append(f"- #{p['number']}: {p['title']}{state}{author}")
    return "\n".join(lines)


def _format_issue_list(issues: list[dict]) -> str:
    lines = []
    for i in issues:
        author = f" @{i['author']}" if i.get("author") else ""
        state = f" ({i['state']})" if i.get("state") else ""
        labels = f" [{', '.join(i['labels'])}]" if i.get("labels") else ""
        lines.append(f"- #{i['number']}: {i['title']}{state}{labels}{author}")
    return "\n".join(lines)


class GitHubListPRsTool(BaseTool):
    name = "github_list_prs"
    description = "List pull requests from the GitHub repository. Defaults to open PRs."
    input_schema = {
        "type": "object",
        "properties": {
            "state": {"type": "string", "enum": ["open", "closed", "all"], "description": "PR state filter (default: open)"},
        },
    }

    def __init__(self, connect: GitHubConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        prs = self._connect.list_prs(state=kwargs.get("state", "open"))
        if not prs:
            return "No pull requests found."
        return _format_pr_list(prs)


class GitHubGetPRTool(BaseTool):
    name = "github_get_pr"
    description = "Get a specific pull request by number with full details."
    input_schema = {
        "type": "object",
        "properties": {"number": {"type": "integer", "description": "PR number"}},
        "required": ["number"],
    }

    def __init__(self, connect: GitHubConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        pr = self._connect.get_pr(kwargs["number"])
        if not pr:
            return f"PR #{kwargs['number']} not found."
        parts = [
            f"#{pr['number']}: {pr['title']}",
            f"State: {pr['state']}",
            f"Author: {pr['author']}",
            f"Branch: {pr['branch']} → {pr['base_branch']}",
        ]
        if pr.get("labels"):
            parts.append(f"Labels: {', '.join(pr['labels'])}")
        if pr.get("reviewers"):
            parts.append(f"Reviewers: {', '.join(pr['reviewers'])}")
        if pr.get("url"):
            parts.append(f"URL: {pr['url']}")
        if pr.get("body"):
            parts.append(f"\nDescription:\n{pr['body'][:1000]}")
        return "\n".join(parts)


class GitHubListIssuesTool(BaseTool):
    name = "github_list_issues"
    description = "List issues from the GitHub repository. Defaults to open issues."
    input_schema = {
        "type": "object",
        "properties": {
            "state": {"type": "string", "enum": ["open", "closed", "all"], "description": "Issue state filter (default: open)"},
        },
    }

    def __init__(self, connect: GitHubConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        issues = self._connect.list_issues(state=kwargs.get("state", "open"))
        if not issues:
            return "No issues found."
        return _format_issue_list(issues)


class GitHubGetIssueTool(BaseTool):
    name = "github_get_issue"
    description = "Get a specific GitHub issue by number with full details."
    input_schema = {
        "type": "object",
        "properties": {"number": {"type": "integer", "description": "Issue number"}},
        "required": ["number"],
    }

    def __init__(self, connect: GitHubConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        issue = self._connect.get_issue(kwargs["number"])
        if not issue:
            return f"Issue #{kwargs['number']} not found."
        parts = [
            f"#{issue['number']}: {issue['title']}",
            f"State: {issue['state']}",
            f"Author: {issue['author']}",
        ]
        if issue.get("assignees"):
            parts.append(f"Assignees: {', '.join(issue['assignees'])}")
        if issue.get("labels"):
            parts.append(f"Labels: {', '.join(issue['labels'])}")
        if issue.get("url"):
            parts.append(f"URL: {issue['url']}")
        if issue.get("body"):
            parts.append(f"\nDescription:\n{issue['body'][:1000]}")
        return "\n".join(parts)


class SavePRTool(BaseTool):
    name = "save_pr"
    description = "Save a pull request to the system of record for future reference and indexing."
    input_schema = {
        "type": "object",
        "properties": {
            "github_id": {"type": "integer"},
            "number": {"type": "integer"},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "state": {"type": "string"},
            "author": {"type": "string"},
            "branch": {"type": "string"},
            "base_branch": {"type": "string"},
            "url": {"type": "string"},
        },
        "required": ["github_id", "number", "title"],
    }

    def __init__(self, connect: GitHubConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        rid = self._connect.ingest_pr(kwargs)
        if rid is None:
            return "PR already stored (duplicate)."
        return f"PR saved as {rid}."


class SaveIssueTool(BaseTool):
    name = "save_issue"
    description = "Save a GitHub issue to the system of record for future reference and indexing."
    input_schema = {
        "type": "object",
        "properties": {
            "github_id": {"type": "integer"},
            "number": {"type": "integer"},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "state": {"type": "string"},
            "author": {"type": "string"},
            "url": {"type": "string"},
        },
        "required": ["github_id", "number", "title"],
    }

    def __init__(self, connect: GitHubConnect) -> None:
        self._connect = connect

    def execute(self, **kwargs: Any) -> str:
        rid = self._connect.ingest_issue(kwargs)
        if rid is None:
            return "Issue already stored (duplicate)."
        return f"Issue saved as {rid}."


# --- Module entry point ---


def get_tools(ctx: ExpertContext) -> GitHubConnect:
    """Entry point called by pearscarf at startup."""
    return GitHubConnect(ctx)
