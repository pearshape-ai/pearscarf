"""Tests for `pearscarf.tools` — `BaseTool.to_api_schema` and `ToolRegistry`."""

from __future__ import annotations

from typing import Any

from pearscarf.tools import BaseTool, ToolRegistry


class _MinimalTool(BaseTool):
    name = "minimal"
    description = "does the minimum"
    input_schema = {"type": "object", "properties": {}}

    def execute(self, **kwargs: Any) -> str:
        return "ok"


class _RichTool(BaseTool):
    name = "rich"
    description = "has properties"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["query"],
    }

    def execute(self, **kwargs: Any) -> str:
        return "ok"


def test_to_api_schema_minimal() -> None:
    schema = _MinimalTool().to_api_schema()
    assert schema == {
        "name": "minimal",
        "description": "does the minimum",
        "input_schema": {"type": "object", "properties": {}},
    }


def test_to_api_schema_rich() -> None:
    schema = _RichTool().to_api_schema()
    assert schema["name"] == "rich"
    assert schema["description"] == "has properties"
    assert schema["input_schema"]["properties"]["query"] == {"type": "string"}
    assert schema["input_schema"]["required"] == ["query"]


def test_registry_register_and_get() -> None:
    reg = ToolRegistry()
    tool = _MinimalTool()
    reg.register(tool)
    assert reg.get("minimal") is tool


def test_registry_register_overrides_same_name() -> None:
    reg = ToolRegistry()
    first = _MinimalTool()
    second = _MinimalTool()
    reg.register(first)
    reg.register(second)
    # ToolRegistry.register stores by name; second registration overrides.
    assert reg.get("minimal") is second


def test_registry_all_schemas_returns_one_per_tool() -> None:
    reg = ToolRegistry()
    reg.register(_MinimalTool())
    reg.register(_RichTool())
    schemas = reg.all_schemas()
    assert len(schemas) == 2
    names = {s["name"] for s in schemas}
    assert names == {"minimal", "rich"}


def test_registry_all_schemas_empty() -> None:
    reg = ToolRegistry()
    assert reg.all_schemas() == []
