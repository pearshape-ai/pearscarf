from __future__ import annotations

import importlib
import inspect
import pkgutil
from abc import ABC, abstractmethod
from typing import Any

import pearscarf.tools as tools_package


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = {}

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        ...

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

    def discover(self) -> None:
        for _importer, mod_name, _ispkg in pkgutil.iter_modules(tools_package.__path__):
            module = importlib.import_module(f"pearscarf.tools.{mod_name}")
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, BaseTool) and obj is not BaseTool and obj.name:
                    self.register(obj())


registry = ToolRegistry()
