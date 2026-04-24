"""Tool framework — `BaseTool` abstract class and `ToolRegistry`.

Concrete tool implementations live in their own modules (e.g.
`pearscarf/graph_access_tools.py` for graph-reading tools shared by
Extraction and Triage, or alongside the consumer they belong to).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = {}

    @abstractmethod
    def execute(self, **kwargs: Any) -> str: ...

    def to_api_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        return self._tools[name]

    def all_schemas(self) -> list[dict[str, Any]]:
        return [t.to_api_schema() for t in self._tools.values()]


registry = ToolRegistry()
