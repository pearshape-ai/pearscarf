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
# Record schema definitions
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: dict[str, list[str]] = {
    "email": ["sender", "subject", "body"],
    "issue": ["linear_id", "title"],
    "issue_change": ["issue_record_id", "field", "changed_at"],
}

OPTIONAL_FIELDS: dict[str, list[str]] = {
    "email": ["recipient", "message_id", "received_at"],
    "issue": [
        "identifier", "description", "status", "priority", "assignee",
        "project", "labels", "comments", "url",
        "linear_created_at", "linear_updated_at",
    ],
    "issue_change": ["from_value", "to_value", "linear_history_id", "changed_by"],
}

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


def _validate_batch(records: list[dict], record_type: str) -> list[str]:
    """Validate all records against the schema for record_type.

    Returns list of error strings. Empty list means all valid.
    """
    required = REQUIRED_FIELDS[record_type]
    allowed = set(required) | set(OPTIONAL_FIELDS[record_type])
    errors: list[str] = []

    for i, rec in enumerate(records):
        label = rec.get("id", rec.get("message_id", f"record[{i}]"))
        if not isinstance(rec, dict):
            errors.append(f"  {label}: not a JSON object")
            continue
        for field in required:
            if field not in rec or rec[field] is None or rec[field] == "":
                errors.append(f"  {label}: missing required field '{field}'")
        unknown = set(rec.keys()) - allowed
        if unknown:
            errors.append(f"  {label}: unknown fields: {', '.join(sorted(unknown))}")

    return errors


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
        "Ingest typed JSON records via direct schema-validated insert. "
        "Accepts a single file or a folder of .json files. "
        "All records must pass validation before any are inserted."
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
                "enum": ["email", "issue", "issue_change"],
                "description": "Type of records",
            },
        },
        "required": ["file_path", "record_type"],
    }

    def execute(self, **kwargs: Any) -> str:
        from pearscarf.storage import store

        file_path = kwargs["file_path"]
        record_type = kwargs["record_type"]

        # --- Load ---
        records = _load_json_records(file_path)
        if isinstance(records, str):
            return records  # error message

        if not records:
            return "Error: no records found."

        # --- Validate ---
        errors = _validate_batch(records, record_type)
        if errors:
            header = f"Validation failed — {len(errors)} error(s), zero inserts:\n"
            return header + "\n".join(errors)

        # --- Insert ---
        saved = 0
        skipped = 0
        record_ids: list[str] = []

        for rec in records:
            if record_type == "email":
                result = store.save_email(
                    source="ingest_expert",
                    sender=rec["sender"],
                    subject=rec["subject"],
                    body=rec["body"],
                    message_id=rec.get("message_id"),
                    recipient=rec.get("recipient", ""),
                    received_at=rec.get("received_at", ""),
                    raw=json.dumps(rec),
                )
                if result is None:
                    skipped += 1
                else:
                    store.classify_record(result, "relevant", reason="ingested via file")
                    record_ids.append(result)
                    saved += 1

            elif record_type == "issue":
                record_id, is_new = store.save_issue(
                    source="ingest_expert",
                    linear_id=rec["linear_id"],
                    identifier=rec.get("identifier", ""),
                    title=rec["title"],
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
                    record_ids.append(record_id)
                    saved += 1
                else:
                    skipped += 1

            elif record_type == "issue_change":
                result = store.save_issue_change(
                    issue_record_id=rec["issue_record_id"],
                    field=rec["field"],
                    from_value=rec.get("from_value", ""),
                    to_value=rec.get("to_value", ""),
                    linear_history_id=rec.get("linear_history_id"),
                    changed_by=rec.get("changed_by", ""),
                    changed_at=rec["changed_at"],
                )
                if result is None:
                    skipped += 1
                else:
                    record_ids.append(result)
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
