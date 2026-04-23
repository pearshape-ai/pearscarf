"""Ingest expert — file-based data entry into PearScarf.

Two ingestion modes:
- Seed files: typed block markdown format
- Record files: typed JSON (email, issue, issue_change) — direct schema-validated insert
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from pearscarf.agents.expert import ExpertAgent
from pearscarf.expert_context import ExpertContext
from pearscarf.knowledge import load as load_prompt
from pearscarf.tools import BaseTool, ToolRegistry

# ---------------------------------------------------------------------------
# Record schema — no hardcoded fields; experts own their record shapes
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json_records(file_path: str) -> list[dict] | str:
    """Load JSON records from a file or folder.

    Returns list of dicts, or an error string.
    """
    if os.path.isdir(file_path):
        records = []
        for root, _dirs, files in os.walk(file_path):
            for fname in sorted(files):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(root, fname)
                with open(fpath) as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    records.extend(data)
                else:
                    records.append(data)
        return records

    if not os.path.isfile(file_path):
        return f"Error: path not found: {file_path}"

    with open(file_path) as fh:
        data = json.load(fh)

    return data if isinstance(data, list) else [data]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


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
        from pearscarf.storage import store

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
        "Ingest typed JSON records from a file or folder. "
        "Delegates record processing to the expert that owns the record_type."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to a JSON file or a folder of JSON files",
            },
            "record_type": {
                "type": "string",
                "description": "Type of records (e.g. 'email', 'issue')",
            },
        },
        "required": ["file_path", "record_type"],
    }

    def execute(self, **kwargs: Any) -> str:
        from pearscarf.extraction.registry import get_registry

        file_path = kwargs["file_path"]
        record_type = kwargs["record_type"]

        # --- Load ---
        records = _load_json_records(file_path)
        if isinstance(records, str):
            return records  # error message

        if not records:
            return "Error: no records found."

        # --- Route to the expert that owns this record type ---
        connect = get_registry().get_connect(record_type)
        if connect is None or not hasattr(connect, "ingest_record"):
            return (
                f"Error: no expert registered for record_type '{record_type}'. "
                f"Make sure the expert is installed and psc run is active."
            )

        saved = 0
        skipped = 0
        record_ids: list[str] = []

        from pearscarf.storage import store

        for rec in records:
            rid = connect.ingest_record(rec)

            if rid is None:
                skipped += 1
            else:
                store.mark_relevant(rid)
                record_ids.append(rid)
                saved += 1

        parts = [f"Saved {saved} {record_type} record(s)."]
        if skipped:
            parts.append(f"Skipped {skipped} duplicate(s).")
        if record_ids:
            parts.append(f"IDs: {', '.join(record_ids)}")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def create_ingest_expert(
    ctx: "ExpertContext",
    on_tool_call=None,
    on_text=None,
    on_tool_result=None,
) -> ExpertAgent:
    """Create an IngestExpert agent."""
    registry = ToolRegistry()
    registry.register(ParseSeedTool())
    registry.register(ParseRecordFileTool())

    return ExpertAgent(
        ctx=ctx,
        domain_prompt=load_prompt("ingest"),
        tool_registry=registry,
        on_tool_call=on_tool_call,
        on_text=on_text,
        on_tool_result=on_tool_result,
    )


def create_ingest_expert_for_runner(
    ctx: "ExpertContext",
) -> Callable:
    """Create a factory function for the AgentRunner.

    Returns agent_factory: Callable[[session_id], ExpertAgent].
    """

    def factory(session_id: str) -> ExpertAgent:
        registry = ToolRegistry()
        registry.register(ParseSeedTool())
        registry.register(ParseRecordFileTool())

        return ExpertAgent(
            ctx=ctx,
            domain_prompt=load_prompt("ingest"),
            tool_registry=registry,
        )

    return factory
