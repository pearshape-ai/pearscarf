"""Extraction prompt testing utility.

Runs the extraction prompt against stored emails and prints results.
No writes to graph, vector store, or any storage. Pure evaluation.

Usage as script:
    python -m pearscaff.extract_test
    python -m pearscaff.extract_test email_042
    python -m pearscaff.extract_test email_001 email_005

Also available as: pearscaff extract-test [record_ids...]
"""

from __future__ import annotations

import json
import sys

import anthropic

from pearscaff.config import ANTHROPIC_API_KEY, MODEL
from pearscaff.db import _get_conn, init_db
from pearscaff.indexer import Indexer
from pearscaff.prompts import load as load_prompt
from pearscaff.tracing import trace_span


def _get_relevant_records() -> list[dict]:
    """Get all records classified as relevant."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, type, source, created_at, raw, human_context "
            "FROM records "
            "WHERE classification = 'relevant' "
            "ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def _get_record(record_id: str) -> dict | None:
    """Get a single record by ID."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, type, source, created_at, raw, human_context "
            "FROM records WHERE id = %s",
            (record_id,),
        ).fetchone()
    return dict(row) if row else None


def _parse_json_response(text: str) -> dict | None:
    """Parse JSON from an LLM response, handling ```json fencing."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def run_extraction(record_ids: list[str] | None = None) -> None:
    """Run extraction prompt against records and print results."""
    init_db()

    indexer = Indexer()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or None)
    prompt_template = load_prompt("extraction")
    entity_types_block = indexer._build_entity_types_block()

    # Resolve records
    if record_ids:
        records = []
        for rid in record_ids:
            record = _get_record(rid)
            if record:
                records.append(record)
            else:
                print(f"Record {rid} not found, skipping.")
    else:
        records = _get_relevant_records()

    if not records:
        print("No records to process.")
        return

    print(f"Processing {len(records)} record(s)...\n")

    for record in records:
        record_id = record["id"]
        record_type = record["type"]

        # Build content
        content = indexer._build_content(record)
        if record.get("human_context"):
            content += f"\n\nAdditional context from human:\n{record['human_context']}"

        # Format prompt
        prompt = prompt_template.format(
            record_type=record_type,
            entity_types_block=entity_types_block,
            record_id=record_id,
            content=content,
        )

        # Print email content
        print("═" * 60)
        print(record_id)
        print("═" * 60)
        print()
        print("--- Email Content ---")
        print(content)
        print()

        # Call Claude
        with trace_span(
            "extract_test",
            run_type="llm",
            metadata={"record_id": record_id, "record_type": record_type},
            inputs={"model": MODEL, "prompt_length": len(prompt)},
        ) as span:
            response = client.messages.create(
                model=MODEL,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            if span:
                span.end(outputs={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                })

        # Extract text from response
        raw_text = ""
        for block in response.content:
            if block.type == "text":
                raw_text += block.text

        # Parse and print result
        print("--- Extraction Result ---")
        parsed = _parse_json_response(raw_text)
        if parsed:
            print(json.dumps(parsed, indent=2))
        else:
            print(f"[JSON parse failed] Raw response:\n{raw_text}")

        print(f"\n(tokens: {response.usage.input_tokens} in / {response.usage.output_tokens} out)")
        print()
# 

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    record_ids = sys.argv[1:] if len(sys.argv) > 1 else None
    run_extraction(record_ids)
