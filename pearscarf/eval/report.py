"""Eval report — terminal formatter and JSON results writer."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone


def print_report(
    aggregate: dict,
    per_record: dict[str, dict],
    pearscarf_version: str,
    dataset_version: str,
) -> None:
    """Print a formatted eval report to the terminal."""
    print()
    print("=" * 55)
    print(f"PearScarf Eval — v{pearscarf_version} vs dataset v{dataset_version}")
    print("=" * 55)
    print()

    print("Per-record results:")
    for record_id, scores in per_record.items():
        if scores["is_noise"]:
            status = "✓" if scores["noise_correctly_empty"] else "✗"
            detail = ""
            if not scores["noise_correctly_empty"]:
                n = scores["entity_extracted"] + scores["fact_extracted"]
                detail = f" (extracted {n} item(s) from noise record)"
            print(f"  {record_id:<20} NOISE {status}{detail}")
        else:
            ent = f"{scores['entity_matched']}/{scores['entity_expected']}"
            fct = f"{scores['fact_matched']}/{scores['fact_expected']}"
            ep = scores["entity_precision"]
            er = scores["entity_recall"]
            fp = scores["fact_precision"]
            fr = scores["fact_recall"]
            print(
                f"  {record_id:<20} entities {ent}  facts {fct}"
                f"  P={fp:.2f}/{ep:.2f}  R={fr:.2f}/{er:.2f}"
            )

    print()
    print("-" * 55)
    print("Aggregate:")
    print(f"  Extraction Precision:          {aggregate['extraction_precision']:.4f}")
    print(f"  Extraction Recall:             {aggregate['extraction_recall']:.4f}")
    print(f"  Graph Fidelity (F1):           {aggregate['graph_fidelity_f1']:.4f}")

    nrr = aggregate.get("noise_rejection_rate")
    if nrr is not None:
        print(f"  Noise Rejection Rate:          {nrr:.4f}")

    era = aggregate.get("entity_resolution_accuracy")
    if era is not None:
        print(f"  Entity Resolution Accuracy:    {era:.4f}")

    ta = aggregate.get("temporal_accuracy")
    if ta is not None:
        print(f"  Temporal Accuracy:             {ta:.4f}")

    print("-" * 55)
    print()


def write_results(
    results_dir: str,
    pearscarf_version: str,
    dataset_version: str,
    aggregate: dict,
    per_record: dict[str, dict],
) -> str:
    """Write results JSON. Returns path written."""
    os.makedirs(results_dir, exist_ok=True)

    # Build serialisable per-record (drop internal counters)
    per_record_out = {}
    for rid, scores in per_record.items():
        per_record_out[rid] = {
            "entity_precision": scores["entity_precision"],
            "entity_recall": scores["entity_recall"],
            "fact_precision": scores["fact_precision"],
            "fact_recall": scores["fact_recall"],
            "is_noise": scores["is_noise"],
            "noise_correctly_empty": scores["noise_correctly_empty"],
        }

    payload = {
        "pearscarf_version": pearscarf_version,
        "dataset_version": dataset_version,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "aggregate": aggregate,
        "per_record": per_record_out,
    }

    filename = f"{pearscarf_version}_{dataset_version}.json"
    path = os.path.join(results_dir, filename)
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)

    print(f"Results written to {path}")
    return path
