from __future__ import annotations

from typing import Any

import httpx

from pearscaff.tools import BaseTool


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web using DuckDuckGo. Returns a summary and top related topics."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            }
        },
        "required": ["query"],
    }

    def execute(self, **kwargs: Any) -> str:
        query = kwargs["query"]
        try:
            resp = httpx.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            parts: list[str] = []

            if data.get("AbstractText"):
                parts.append(f"Summary: {data['AbstractText']}")
                if data.get("AbstractURL"):
                    parts.append(f"Source: {data['AbstractURL']}")

            if data.get("Answer"):
                parts.append(f"Answer: {data['Answer']}")

            topics = data.get("RelatedTopics", [])[:5]
            for topic in topics:
                if "Text" in topic:
                    parts.append(f"- {topic['Text']}")

            if not parts:
                return f"No results found for '{query}'."

            return "\n".join(parts)
        except Exception as exc:
            return f"Search error: {exc}"
