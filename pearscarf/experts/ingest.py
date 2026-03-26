"""Ingest expert — file-based data entry into PearScarf.

Two ingestion modes:
- Seed files: typed block markdown format
- Record files: typed JSON (email, issue, issue_change)
"""

from __future__ import annotations

import json
import os
from typing import Any

from pearscarf.agents.expert import ExpertAgent
from pearscarf.prompts import load as load_prompt
from pearscarf.tools import BaseTool, ToolRegistry


class ParseSeedTool(BaseTool):
    name = "parse_seed"
    description = (
        "Read and parse a seed file in typed block markdown format. "
        "Saves it to the system of record and returns the assigned record_id."
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
        from pearscarf import store

        file_path = kwargs["file_path"]
        if not os.path.isfile(file_path):
            return f"Error: file not found: {file_path}"

        with open(file_path) as fh:
            raw = fh.read()

        if not raw.strip():
            return f"Error: file is empty: {file_path}"

        record_id = store.save_ingest(
            source="ingest_expert",
            raw=raw,
        )
        return f"Seed file saved as {record_id}."


class ParseRecordFileTool(BaseTool):
    name = "parse_record_file"
    description = (
        "Read and parse a typed JSON record file. "
        "Saves records to the system of record and returns count saved."
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
        from pearscarf import store

        file_path = kwargs["file_path"]
        record_type = kwargs["record_type"]

        if not os.path.isfile(file_path):
            return f"Error: file not found: {file_path}"

        with open(file_path) as fh:
            data = json.load(fh)

        # Accept a single record dict or a list
        records = data if isinstance(data, list) else [data]

        saved = 0
        skipped = 0

        for rec in records:
            if record_type == "email":
                result = store.save_email(
                    source="ingest_expert",
                    sender=rec.get("sender", ""),
                    subject=rec.get("subject", ""),
                    body=rec.get("body", ""),
                    message_id=rec.get("message_id"),
                    recipient=rec.get("recipient", ""),
                    received_at=rec.get("received_at", ""),
                    raw=json.dumps(rec),
                )
                if result is None:
                    skipped += 1
                else:
                    store.classify_record(result, "relevant", reason="ingested via file")
                    saved += 1

            elif record_type == "issue":
                record_id, is_new = store.save_issue(
                    source="ingest_expert",
                    linear_id=rec.get("linear_id", rec.get("id", "")),
                    identifier=rec.get("identifier", ""),
                    title=rec.get("title", ""),
                    description=rec.get("description", ""),
                    status=rec.get("status", ""),
                    priority=rec.get("priority", ""),
                    assignee=rec.get("assignee", ""),
                    project=rec.get("project", ""),
                    labels=rec.get("labels"),
                    comments=rec.get("comments"),
                    url=rec.get("url", ""),
                    linear_created_at=rec.get("linear_created_at", ""),
                    linear_updated_at=rec.get("linear_updated_at", ""),
                    raw=json.dumps(rec),
                )
                if is_new:
                    store.classify_record(record_id, "relevant", reason="ingested via file")
                    saved += 1
                else:
                    skipped += 1

            elif record_type == "issue_change":
                result = store.save_issue_change(
                    issue_record_id=rec.get("issue_record_id", ""),
                    field=rec.get("field", ""),
                    from_value=rec.get("from_value", ""),
                    to_value=rec.get("to_value", ""),
                    linear_history_id=rec.get("linear_history_id"),
                    changed_by=rec.get("changed_by", ""),
                    changed_at=rec.get("changed_at", ""),
                )
                if result is None:
                    skipped += 1
                else:
                    saved += 1  # already auto-classified by save_issue_change

        parts = [f"Saved {saved} {record_type} record(s)."]
        if skipped:
            parts.append(f"Skipped {skipped} duplicate(s).")
        return " ".join(parts)


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
