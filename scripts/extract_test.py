"""Extraction prompt testing utility.

Runs the extraction prompt against stored records and prints results.
No writes to graph, vector store, or any storage. Pure evaluation.

Usage:
    python scripts/extract_test.py                       # all relevant records
    python scripts/extract_test.py email_042             # single record
    python scripts/extract_test.py email_001 email_005   # multiple records
"""

from __future__ import annotations

import json
import sys

import anthropic
from dotenv import load_dotenv

load_dotenv()

from pearscarf.config import (
    ANTHROPIC_API_KEY,
    EXTRACTION_MAX_TOKENS,
    EXTRACTION_MODEL,
    EXTRACTION_TEMPERATURE,
)
from pearscarf.db import _get_conn, init_db
from pearscarf.graph import FACT_CATEGORIES
from pearscarf.indexer import Indexer
from pearscarf.prompts import load as load_prompt
from pearscarf.tracing import trace_span


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
    system_prompt = load_prompt("extraction")

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

    print(f"Processing {len(records)} record(s)...")
    print(f"Model: {EXTRACTION_MODEL}  Temperature: {EXTRACTION_TEMPERATURE}  Max tokens: {EXTRACTION_MAX_TOKENS}\n")

    for record in records:
        record_id = record["id"]
        record_type = record["type"]

        # Build content
        content = indexer._build_content(record)
        if record.get("human_context"):
            content += f"\n\nAdditional context from human:\n{record['human_context']}"

        # User message — fixed template, not in prompt file
        user_message = f"Record ({record_id}, {record_type}):\n\n{content}"

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
            inputs={"model": EXTRACTION_MODEL, "prompt_length": len(user_message)},
        ) as span:
            response = client.messages.create(
                model=EXTRACTION_MODEL,
                max_tokens=EXTRACTION_MAX_TOKENS,
                temperature=EXTRACTION_TEMPERATURE,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
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
            # Print entities
            entities = parsed.get("entities", [])
            entity_names = {e.get("name", "") for e in entities}
            print(f"\nEntities ({len(entities)}):")
            for e in entities:
                meta = e.get("metadata", {})
                meta_str = ", ".join(f"{k}={v}" for k, v in meta.items()) if meta else ""
                extra = f"  [{meta_str}]" if meta_str else ""
                print(f"  [{e.get('type', '?')}] {e.get('name', '?')}{extra}")

            # Print facts grouped by edge_label
            facts = parsed.get("facts", [])

            # Detect old extraction format
            if any("category" in f and "edge_label" not in f for f in facts):
                print(f"\n⚠ Old extraction format detected: facts use 'category' instead of 'edge_label'")

            print(f"\nFacts ({len(facts)}):")
            by_label: dict[str, list] = {}
            warnings = []
            for f in facts:
                label = f.get("edge_label", "UNKNOWN")
                by_label.setdefault(label, []).append(f)
                # Validate from_entity exists
                from_e = f.get("from_entity", "")
                if from_e and from_e not in entity_names:
                    warnings.append(f"  ⚠ from_entity '{from_e}' not in entities array")
                to_e = f.get("to_entity")
                if to_e and to_e not in entity_names:
                    warnings.append(f"  ⚠ to_entity '{to_e}' not in entities array")
                # Validate edge_label and fact_type
                if label not in FACT_CATEGORIES:
                    warnings.append(f"  ⚠ unrecognized edge_label '{label}'")
                else:
                    ft = f.get("fact_type", "")
                    if ft and ft not in FACT_CATEGORIES[label]:
                        warnings.append(f"  ⚠ unrecognized fact_type '{ft}' for {label}")

            for label, label_facts in sorted(by_label.items()):
                print(f"\n  {label}:")
                for f in label_facts:
                    ft = f.get("fact_type", "?")
                    to_str = f" → {f['to_entity']}" if f.get("to_entity") else ""
                    valid = f"  (valid_until: {f['valid_until']})" if f.get("valid_until") else ""
                    print(f"    [{f.get('confidence', '?')}] {ft}: {f.get('from_entity', '?')}{to_str}: {f.get('fact', '')}{valid}")

            if warnings:
                print(f"\nWarnings ({len(warnings)}):")
                for w in warnings:
                    print(w)
        else:
            print(f"[JSON parse failed] Raw response:\n{raw_text}")

        print(f"\n(tokens: {response.usage.input_tokens} in / {response.usage.output_tokens} out)")
        print()
# 

if __name__ == "__main__":
    record_ids = sys.argv[1:] if len(sys.argv) > 1 else None
    run_extraction(record_ids)
