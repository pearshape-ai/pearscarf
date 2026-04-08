"""Eval runner — graph-based evaluation pipeline.

Usage: psc eval --dataset <path>

Pipeline:
    1. Ingest seed (if present)
    2. Ingest records via ParseRecordFileTool
    3. Wait for indexer to process all records
    4. Query graph for entities and facts per record
    5. Score against ground truth
    6. Report and write results
"""

from __future__ import annotations

import json
import os
import re
import time

from pearscarf.storage import graph
from pearscarf.eval import scoring
from pearscarf.config import EXTRACTION_MODEL, EXTRACTION_TEMPERATURE, EXTRACTION_MAX_TOKENS
from pearscarf.storage.db import _get_conn, init_db
from pearscarf.eval.report import print_report, write_results
from pearscarf.experts.ingest import ParseRecordFileTool


# --- Dataset loading helpers ---


def _read_dataset_version(dataset_path: str, ground_truth: dict) -> str:
    """Resolve dataset version from ground truth or dimensions.md."""
    version = ground_truth.get("version")
    if version:
        return str(version)

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


def _load_ground_truth(dataset_path: str) -> tuple[dict, dict, str]:
    """Load ground truth and resolve dataset version.

    Returns (gt_records, ground_truth_raw, dataset_version).
    """
    gt_path = os.path.join(dataset_path, "ground_truth.json")
    if not os.path.isfile(gt_path):
        raise SystemExit(f"Ground truth not found: {gt_path}")
    with open(gt_path) as fh:
        ground_truth = json.load(fh)

    dataset_version = _read_dataset_version(dataset_path, ground_truth)

    if "records" in ground_truth and isinstance(ground_truth["records"], dict):
        gt_records = ground_truth["records"]
    else:
        gt_records = {
            k: v for k, v in ground_truth.items()
            if isinstance(v, dict)
        }

    return gt_records, ground_truth, dataset_version


# --- Graph query helpers ---


def _graph_is_empty() -> bool:
    """Check if Neo4j has any nodes."""
    stats = graph.graph_stats()
    return stats.get("total_entities", 0) == 0 and stats.get("day_nodes", 0) == 0


def _pending_record_count() -> int:
    """Count records awaiting indexing."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM records "
            "WHERE indexed = FALSE AND classification = 'relevant'"
        ).fetchone()
        return row["c"]


def _build_extracted_from_graph(record_id: str) -> dict:
    """Query the graph for entities and facts sourced from a record.

    Returns {"entities": [...], "facts": [...]} matching the shape
    that scoring.score_record() expects.
    """
    items = graph.get_nodes_by_source_record(record_id)

    # Collect unique entities from the from/to fields
    entity_set: dict[str, dict] = {}  # name -> entity dict
    facts = []

    for item in items:
        from_name = item.get("from", "")
        to_name = item.get("to", "")
        edge_label = item.get("edge_label", "")

        # Build fact
        fact = {
            "edge_label": edge_label,
            "fact_type": item.get("fact_type", ""),
            "fact": item.get("fact", ""),
            "from_entity": from_name,
            "to_entity": to_name if to_name and not _is_day(to_name) else None,
            "confidence": item.get("confidence", ""),
            "source_at": item.get("source_at", ""),
            "stale": item.get("stale", False),
            "valid_until": item.get("valid_until"),
        }
        facts.append(fact)

        # Collect entities (skip Day nodes)
        if from_name and not _is_day(from_name):
            if from_name not in entity_set:
                entity_set[from_name] = {"name": from_name, "type": item.get("from_type", "")}
        if to_name and not _is_day(to_name):
            if to_name not in entity_set:
                entity_set[to_name] = {"name": to_name, "type": item.get("to_type", "")}

    # Enrich entities with aliases from IDENTIFIED_AS edges
    for ent in entity_set.values():
        aliases = _get_aliases(ent["name"])
        if aliases:
            ent["aliases"] = aliases

    return {
        "entities": list(entity_set.values()),
        "facts": facts,
    }


def _get_aliases(entity_name: str) -> list[str]:
    """Get surface forms that resolved to this entity via IDENTIFIED_AS edges."""
    with graph.get_session() as session:
        result = session.run(
            "MATCH (n)-[r:IDENTIFIED_AS]->(n) "
            "WHERE toLower(n.name) = toLower($name) AND r.surface_form IS NOT NULL "
            "RETURN r.surface_form AS sf",
            name=entity_name,
        )
        return [r["sf"] for r in result if r["sf"].lower() != entity_name.lower()]


def _is_day(name: str) -> bool:
    """Check if a name looks like a Day node date (YYYY-MM-DD)."""
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", name))


# --- Verbose output ---


def _print_verbose_graph(
    record_id: str,
    extracted: dict,
    expected: dict,
) -> None:
    """Print detailed debug output for a single record."""
    print()
    print("=" * 60)
    print(record_id)
    print("=" * 60)

    print("\n--- Expected Entities ---")
    for e in expected.get("expected_entities", []):
        meta = e.get("metadata", {})
        meta_str = ", ".join(f"{k}={v}" for k, v in meta.items()) if meta else ""
        extra = f"  [{meta_str}]" if meta_str else ""
        print(f"  [{e.get('type', '?')}] {e.get('name', '?')}{extra}")

    print("\n--- Expected Facts ---")
    for f in expected.get("expected_facts", []):
        to_str = f" -> {f['to_entity']}" if f.get("to_entity") else ""
        valid = f"  (valid_until: {f['valid_until']})" if f.get("valid_until") else ""
        label = f"{f.get('edge_label', '?')}/{f.get('fact_type', '?')}"
        print(f"  [{f.get('confidence', '?')}] {label}: {f.get('from_entity', '?')}{to_str}{valid}")

    print("\n--- Graph Entities ---")
    for e in extracted.get("entities", []):
        print(f"  {e.get('name', '?')}")

    print("\n--- Graph Facts ---")
    for f in extracted.get("facts", []):
        to_str = f" -> {f['to_entity']}" if f.get("to_entity") else ""
        valid = f"  (valid_until: {f['valid_until']})" if f.get("valid_until") else (
            f"  (source_at: {f['source_at']})" if f.get("source_at") else ""
        )
        label = f"{f.get('edge_label', '?')}/{f.get('fact_type', '?')}"
        print(f"  [{f.get('confidence', '?')}] {label}: {f.get('from_entity', '?')}{to_str}{valid}")

    print()


# --- Main pipeline ---


def run_graph_eval(dataset_path: str, *, verbose: bool = False) -> None:
    """Graph-based eval: ingest -> index -> query graph -> score."""
    from pearscarf import __version__ as pearscarf_version
    from pearscarf.storage import store

    init_db()

    # Load ground truth
    gt_records, ground_truth, dataset_version = _load_ground_truth(dataset_path)

    print(f"PearScarf v{pearscarf_version} — graph eval against dataset v{dataset_version}")
    print(f"Model: {EXTRACTION_MODEL}  Temperature: {EXTRACTION_TEMPERATURE}  Max tokens: {EXTRACTION_MAX_TOKENS}")
    print(f"Ground truth entries: {len(gt_records)}")
    print()

    # --- Require clean graph ---
    if not _graph_is_empty():
        raise SystemExit(
            "Neo4j graph is not empty — eval requires a clean graph.\n"
            "Run `python scripts/reindex_all.py` to wipe and retry."
        )

    # --- Step 1: Seed ---
    seed_path = os.path.join(dataset_path, "seed.md")
    if os.path.isfile(seed_path):
        with open(seed_path) as fh:
            seed_content = fh.read()
        record_id = store.save_ingest(source="eval_runner", raw=seed_content)
        print(f"Seed ingested as {record_id}")
    else:
        print("Warning: no seed.md found — proceeding without seed")

    # --- Step 2: Ingest records ---
    tool = ParseRecordFileTool()
    data_dir = os.path.join(dataset_path, "data")

    type_map = {
        "emails": "email",
        "issues": "issue",
        "issue_changes": "issue_change",
    }

    for folder_name, record_type in type_map.items():
        folder_path = os.path.join(data_dir, folder_name)
        if not os.path.isdir(folder_path):
            continue
        result = tool.execute(file_path=folder_path, record_type=record_type)
        print(f"  {folder_name}: {result}")
        if result.startswith("Validation failed"):
            raise SystemExit(f"Record ingestion failed for {folder_name} — aborting eval.")

    print()

    # --- Step 3: Wait for indexer ---
    print("Waiting for indexer...")
    start = time.time()
    while True:
        pending = _pending_record_count()
        if pending == 0:
            print("Indexer finished — all records processed.")
            break
        elapsed = int(time.time() - start)
        print(f"  {pending} record(s) remaining... ({elapsed}s)")
        time.sleep(2)

    print()

    # --- Step 4: Query graph and score ---
    per_record: dict[str, dict] = {}
    extracted_entities_by_record: dict[str, list[dict]] = {}
    extracted_facts_by_record: dict[str, list[dict]] = {}

    for record_id, expected in gt_records.items():
        extracted = _build_extracted_from_graph(record_id)

        extracted_entities_by_record[record_id] = extracted.get("entities", [])
        extracted_facts_by_record[record_id] = extracted.get("facts", [])

        scores = scoring.score_record(extracted, expected)
        per_record[record_id] = scores

        if verbose:
            _print_verbose_graph(record_id, extracted, expected)

        # Confidence warnings
        for w in scores.get("confidence_warnings", []):
            print(f"    ⚠ confidence: {w}")

        # Progress
        if scores["is_noise"]:
            status = "ok" if scores["noise_correctly_empty"] else "FAIL"
            print(f"  {record_id}: noise — {status}")
        else:
            print(
                f"  {record_id}: entities {scores['entity_matched']}/{scores['entity_expected']}"
                f"  facts {scores['fact_matched']}/{scores['fact_expected']}"
            )

    # --- Step 5: Aggregate and report ---
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

    # Per-label F1
    per_label = {}
    for label in ("affiliated", "asserted", "transitioned"):
        lm = sum(r.get(f"{label}_matched", 0) for r in per_record.values())
        le = sum(r.get(f"{label}_extracted", 0) for r in per_record.values())
        lx = sum(r.get(f"{label}_expected", 0) for r in per_record.values())
        lp = scoring.precision(lm, le)
        lr = scoring.recall(lm, lx)
        per_label[label] = {"precision": lp, "recall": lr, "f1": scoring.f1(lp, lr)}
    aggregate["per_label_f1"] = per_label

    # ERA (optional)
    resolution_pairs = ground_truth.get("resolution_pairs")
    if resolution_pairs:
        era = scoring.entity_resolution_accuracy(
            resolution_pairs, extracted_entities_by_record,
            extracted_facts_by_record=extracted_facts_by_record,
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

    print_report(aggregate, per_record, pearscarf_version, dataset_version)

    results_dir = os.path.join(dataset_path, "results")
    write_results(results_dir, pearscarf_version, dataset_version, aggregate, per_record)
