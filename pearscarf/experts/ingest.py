"""Ingest expert — file-based data entry into PearScarf.

Two ingestion modes:
- Seed files: typed block markdown format
- Record files: typed JSON (email, issue, issue_change)

Tools are stubs in this version — no parsing or storage logic.
"""

from __future__ import annotations

from typing import Any

from pearscarf.agents.expert import ExpertAgent
from pearscarf.prompts import load as load_prompt
from pearscarf.tools import BaseTool, ToolRegistry


class ParseSeedTool(BaseTool):
    name = "parse_seed"
    description = (
        "Read and parse a seed file in typed block markdown format. "
        "Returns structured content extracted from the file."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the seed .md file",
            },
        },
        "required": ["file_path"],
    }

    def execute(self, **kwargs: Any) -> str:
        return "parse_seed is not yet implemented."


class ParseRecordFileTool(BaseTool):
    name = "parse_record_file"
    description = (
        "Read and parse a typed JSON record file. "
        "Returns parsed records from the file."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the JSON record file",
            },
            "record_type": {
                "type": "string",
                "enum": ["email", "issue", "issue_change"],
                "description": "Type of records in the file",
            },
        },
        "required": ["file_path", "record_type"],
    }

    def execute(self, **kwargs: Any) -> str:
        return "parse_record_file is not yet implemented."


def create_ingest_expert(
    on_tool_call=None,
    on_text=None,
    on_tool_result=None,
) -> ExpertAgent:
    """Create an IngestExpert agent for standalone use."""
    registry = ToolRegistry()
    registry.register(ParseSeedTool())
    registry.register(ParseRecordFileTool())

    return ExpertAgent(
        domain="ingest",
        domain_prompt=load_prompt("ingest"),
        tool_registry=registry,
        on_tool_call=on_tool_call,
        on_text=on_text,
        on_tool_result=on_tool_result,
    )


def create_ingest_expert_for_runner(
    bus=None,
) -> callable:
    """Create a factory function for the AgentRunner.

    Returns agent_factory: Callable[[session_id], ExpertAgent].
    """

    def factory(session_id: str) -> ExpertAgent:
        registry = ToolRegistry()
        registry.register(ParseSeedTool())
        registry.register(ParseRecordFileTool())

        return ExpertAgent(
            domain="ingest",
            domain_prompt=load_prompt("ingest"),
            tool_registry=registry,
            bus=bus,
            agent_name="ingest_expert",
        )

    return factory
