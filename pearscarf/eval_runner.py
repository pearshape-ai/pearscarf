"""Eval runner — loads a dataset, runs extraction on each record, scores, reports.

Usage: psc eval --dataset <path>

Dataset structure:
    <path>/
    ├── data/
    │   ├── emails/           # email record JSON files
    │   ├── issues/           # issue record JSON files
    │   └── issue_changes/    # issue change record JSON files
    ├── ground_truth.json     # expected output + optional resolution_pairs/temporal_assertions
    ├── dimensions.md         # contains dataset version
    └── results/              # created by eval runner on first run
"""

from __future__ import annotations

import json
import os
import re

import anthropic

from pearscarf import scoring
from pearscarf.config import (
    ANTHROPIC_API_KEY,
    EXTRACTION_MAX_TOKENS,
    EXTRACTION_MODEL,
    EXTRACTION_TEMPERATURE,
)
from pearscarf.eval_report import print_report, write_results
from pearscarf.prompts import load as load_prompt
from pearscarf.tracing import trace_span


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


def _read_dataset_version(dataset_path: str, ground_truth: dict) -> str:
    """Resolve dataset version from ground truth or dimensions.md."""
    # 1. Check ground_truth.json for "version" key
    version = ground_truth.get("version")
    if version:
        return str(version)

    # 2. Check dimensions.md for a version: field or (vX.Y.Z) in the heading
    dim_path = os.path.join(dataset_path, "dimensions.md")
    if os.path.isfile(dim_path):
        with open(dim_path) as fh:
            content = fh.read()
        match = re.search(r"^version:\s*(.+)$", content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        match = re.search(r"\(v([\d.]+)\)", content)
        if match:
            return match.group(1)

    return "unknown"


def _load_records(data_dir: str) -> list[dict]:
    """Load record JSON files from data/ subdirectories (emails/, issues/, etc.).

    Walks all subdirectories and sorts by created_at then id for
    chronological order.
    """
    records = []
    for root, _dirs, files in os.walk(data_dir):
        for filename in files:
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(root, filename)
            with open(filepath) as fh:
                records.append(json.load(fh))
    records.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    return records


def _print_verbose(
    record_id: str,
    content: str,
    extracted: dict,
    expected: dict,
) -> None:
    """Print detailed debug output for a single record."""
    print()
    print("=" * 60)
    print(record_id)
    print("=" * 60)

    print("\n--- Record Content ---")
    print(content)

    print("\n--- Expected Entities ---")
    for e in expected.get("expected_entities", []):
        meta = e.get("metadata", {})
        meta_str = ", ".join(f"{k}={v}" for k, v in meta.items()) if meta else ""
        extra = f"  [{meta_str}]" if meta_str else ""
        print(f"  [{e.get('type', '?')}] {e.get('name', '?')}{extra}")

    print("\n--- Expected Facts ---")
    for f in expected.get("expected_facts", []):
        to_str = f" -> {f['to_entity']}" if f.get("to_entity") else ""
        valid = f"  (valid_at: {f['valid_at']})" if f.get("valid_at") else ""
        print(f"  [{f.get('confidence', '?')}] {f.get('category', '?')}: {f.get('from_entity', '?')}{to_str}{valid}")

    print("\n--- Extracted Entities ---")
    for e in extracted.get("entities", []):
        meta = e.get("metadata", {})
        meta_str = ", ".join(f"{k}={v}" for k, v in meta.items()) if meta else ""
        extra = f"  [{meta_str}]" if meta_str else ""
        print(f"  [{e.get('type', '?')}] {e.get('name', '?')}{extra}")

    print("\n--- Extracted Facts ---")
    for f in extracted.get("facts", []):
        to_str = f" -> {f['to_entity']}" if f.get("to_entity") else ""
        valid = f"  (valid_at: {f['valid_at']})" if f.get("valid_at") else ""
        print(f"  [{f.get('confidence', '?')}] {f.get('category', '?')}: {f.get('from_entity', '?')}{to_str}{valid}")

    print()


def run_eval(dataset_path: str, *, verbose: bool = False) -> None:
    """Load dataset, run extraction on each record, score, report, write results."""
    from pearscarf import __version__ as pearscarf_version

    # Load ground truth
    gt_path = os.path.join(dataset_path, "ground_truth.json")
    if not os.path.isfile(gt_path):
        raise SystemExit(f"Ground truth not found: {gt_path}")
    with open(gt_path) as fh:
        ground_truth = json.load(fh)

    dataset_version = _read_dataset_version(dataset_path, ground_truth)

    # Ground truth supports two layouts:
    #   Nested:  {"version": "...", "records": {"email_001": {...}, ...}}
    #   Flat:    {"email_001": {...}, ..., "resolution_pairs": [...], ...}
    if "records" in ground_truth and isinstance(ground_truth["records"], dict):
        gt_records = ground_truth["records"]
    else:
        gt_records = {
            k: v for k, v in ground_truth.items()
            if isinstance(v, dict)
        }

    # Load records
    data_dir = os.path.join(dataset_path, "data")
    if not os.path.isdir(data_dir):
        raise SystemExit(f"Data directory not found: {data_dir}")
    records = _load_records(data_dir)

    if not records:
        raise SystemExit("No record files found in data/")

    # Validate coverage
    record_ids = {r["id"] for r in records}
    gt_ids = set(gt_records.keys())
    missing_gt = record_ids - gt_ids
    if missing_gt:
        print(f"Warning: {len(missing_gt)} record(s) have no ground truth: {', '.join(sorted(missing_gt))}")
    extra_gt = gt_ids - record_ids
    if extra_gt:
        print(f"Warning: {len(extra_gt)} ground truth entries have no record file: {', '.join(sorted(extra_gt))}")

    # Setup extraction
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or None)
    system_prompt = load_prompt("extraction")

    print(f"PearScarf v{pearscarf_version} — eval against dataset v{dataset_version}")
    print(f"Model: {EXTRACTION_MODEL}  Temperature: {EXTRACTION_TEMPERATURE}  Max tokens: {EXTRACTION_MAX_TOKENS}")
    print(f"Records: {len(records)}  Ground truth entries: {len(gt_records)}")
    print()

    # Run extraction + scoring per record
    per_record: dict[str, dict] = {}
    extracted_entities_by_record: dict[str, list[dict]] = {}
    extracted_facts_by_record: dict[str, list[dict]] = {}

    for record in records:
        record_id = record["id"]
        record_type = record.get("type", "email")
        content = record.get("content", "")

        if record.get("human_context"):
            content += f"\n\nAdditional context from human:\n{record['human_context']}"

        user_message = f"Record ({record_id}, {record_type}):\n\n{content}"

        # Call extraction LLM
        with trace_span(
            "eval_extract",
            run_type="llm",
            metadata={
                "record_id": record_id,
                "record_type": record_type,
                "dataset_version": dataset_version,
                "pearscarf_version": pearscarf_version,
            },
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

        # Parse response
        raw_text = ""
        for block in response.content:
            if block.type == "text":
                raw_text += block.text

        extracted = _parse_json_response(raw_text) or {}

        # Store for ERA / Temporal Accuracy
        extracted_entities_by_record[record_id] = extracted.get("entities", [])
        extracted_facts_by_record[record_id] = extracted.get("facts", [])

        # Score against ground truth
        expected = gt_records.get(record_id)
        if expected is None:
            print(f"  {record_id}: skipped (no ground truth)")
            continue

        scores = scoring.score_record(extracted, expected)
        per_record[record_id] = scores

        if verbose:
            _print_verbose(record_id, content, extracted, expected)

        # Progress indicator
        if scores["is_noise"]:
            status = "ok" if scores["noise_correctly_empty"] else "FAIL"
            print(f"  {record_id}: noise — {status}")
        else:
            print(
                f"  {record_id}: entities {scores['entity_matched']}/{scores['entity_expected']}"
                f"  facts {scores['fact_matched']}/{scores['fact_expected']}"
            )

    # Aggregate metrics
    total_fact_matched = sum(r["fact_matched"] for r in per_record.values())
    total_fact_extracted = sum(r["fact_extracted"] for r in per_record.values())
    total_fact_expected = sum(r["fact_expected"] for r in per_record.values())

    agg_precision = scoring.precision(total_fact_matched, total_fact_extracted)
    agg_recall = scoring.recall(total_fact_matched, total_fact_expected)
    agg_f1 = scoring.f1(agg_precision, agg_recall)
    agg_nrr = scoring.noise_rejection_rate(list(per_record.values()))

    aggregate: dict = {
        "extraction_precision": agg_precision,
        "extraction_recall": agg_recall,
        "graph_fidelity_f1": agg_f1,
    }
    if agg_nrr is not None:
        aggregate["noise_rejection_rate"] = agg_nrr

    # ERA (optional)
    resolution_pairs = ground_truth.get("resolution_pairs")
    if resolution_pairs:
        era = scoring.entity_resolution_accuracy(
            resolution_pairs, extracted_entities_by_record
        )
        if era is not None:
            aggregate["entity_resolution_accuracy"] = era

    # Temporal Accuracy (optional)
    temporal_assertions = ground_truth.get("temporal_assertions")
    if temporal_assertions:
        ta = scoring.temporal_accuracy(
            temporal_assertions, extracted_facts_by_record
        )
        if ta is not None:
            aggregate["temporal_accuracy"] = ta

    # Report
    print_report(aggregate, per_record, pearscarf_version, dataset_version)

    # Write results
    results_dir = os.path.join(dataset_path, "results")
    write_results(results_dir, pearscarf_version, dataset_version, aggregate, per_record)
