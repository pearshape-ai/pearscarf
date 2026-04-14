"""Eval runner — dataset-driven evaluation pipeline.

Usage:
    psc eval er --dataset <path>       # ER scoring only
    psc eval --dataset <path>          # all available eval types

Pipeline:
    1. Read dataset.yaml for config
    2. Read sequence.yaml for record order (if present)
    3. Ingest seed (if present)
    4. Ingest records in sequence order
    5. Wait for indexer to process all records
    6. Score against ground truth
    7. Print results
"""

from __future__ import annotations

import importlib
import json
import os
import time

import yaml

from pearscarf import __version__ as pearscarf_version
from pearscarf.config import EXTRACTION_MODEL, EXTRACTION_TEMPERATURE, EXTRACTION_MAX_TOKENS
from pearscarf.storage import graph
from pearscarf.storage.db import _get_conn, init_db


# --- Dataset loading ---


def _load_dataset_config(dataset_path: str) -> dict:
    """Load dataset.yaml. Falls back to minimal defaults if absent."""
    cfg_path = os.path.join(dataset_path, "dataset.yaml")
    if os.path.isfile(cfg_path):
        with open(cfg_path) as fh:
            return yaml.safe_load(fh) or {}

    # Legacy fallback: derive data_map from folder names
    data_dir = os.path.join(dataset_path, "data")
    data_map = {}
    if os.path.isdir(data_dir):
        for name in sorted(os.listdir(data_dir)):
            if os.path.isdir(os.path.join(data_dir, name)):
                data_map[name] = name
    return {"data_map": data_map}


def _load_sequence(dataset_path: str) -> list[str] | None:
    """Load sequence.yaml if present. Returns ordered list of record keys."""
    seq_path = os.path.join(dataset_path, "sequence.yaml")
    if os.path.isfile(seq_path):
        with open(seq_path) as fh:
            return yaml.safe_load(fh) or []
    return None


# --- Ingestion helpers ---


def _ensure_expert_connects():
    """Load expert connects so ingest tools can delegate."""
    from pearscarf.bus import MessageBus
    from pearscarf.expert_context import build_context
    from pearscarf.indexing.registry import get_registry

    bus = MessageBus()
    registry = get_registry()
    for expert in registry.enabled_experts():
        if not expert.tools_module:
            continue
        try:
            tools_mod = importlib.import_module(expert.tools_module)
            ctx = build_context(expert.name, bus, expert_version=expert.version)
            connect = tools_mod.get_tools(ctx)
            for rt in expert.record_types:
                registry.register_connect(rt, connect)
        except Exception as exc:
            print(f"  {expert.name} tools failed: {exc}")


def _ingest_file(file_path: str, record_type: str) -> str | None:
    """Ingest a single JSON file. Returns record_id or None."""
    from pearscarf.indexing.registry import get_registry
    from pearscarf.storage import store

    with open(file_path) as fh:
        data = json.load(fh)

    connect = get_registry().get_connect(record_type)
    if connect is None or not hasattr(connect, "ingest_record"):
        print(f"    Error: no expert for record_type '{record_type}'")
        return None

    rid = connect.ingest_record(data)
    if rid:
        store.mark_relevant(rid)
    return rid


def _resolve_record_file(
    record_key: str, data_dir: str, data_map: dict
) -> tuple[str, str] | None:
    """Resolve a record key (e.g. 'email_001') to (file_path, record_type).

    Walks data_map folders looking for {record_key}.json.
    """
    for folder_name, record_type in data_map.items():
        folder_path = os.path.join(data_dir, folder_name)
        if not os.path.isdir(folder_path):
            continue
        file_path = os.path.join(folder_path, f"{record_key}.json")
        if os.path.isfile(file_path):
            return file_path, record_type
    return None


def _pending_record_count() -> int:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM records "
            "WHERE indexed = FALSE AND classification = 'relevant'"
        ).fetchone()
        return dict(row).get("c", 0) if row else 0


def _graph_is_empty() -> bool:
    stats = graph.graph_stats()
    return stats.get("total_entities", 0) == 0 and stats.get("day_nodes", 0) == 0


def _wait_for_indexer():
    """Block until all relevant records are indexed."""
    print("Waiting for indexer...")
    start = time.time()
    while True:
        pending = _pending_record_count()
        if pending == 0:
            print("Indexer finished.")
            break
        elapsed = int(time.time() - start)
        print(f"  {pending} record(s) remaining... ({elapsed}s)")
        time.sleep(2)


# --- Graph queries for ER ---


def _get_all_graph_entities() -> list[dict]:
    """Get all entity nodes from Neo4j (excluding Day nodes).

    Returns list of {"name", "type", "aliases"}.
    """
    entities = []
    labels = {"Person": "person", "Company": "company", "Project": "project",
              "Event": "event", "Repository": "repository"}
    with graph.get_session() as session:
        for neo_label, type_name in labels.items():
            result = session.run(
                f"MATCH (n:{neo_label}) RETURN n.name AS name, elementId(n) AS eid"
            )
            for record in result:
                name = record["name"]
                eid = record["eid"]
                # Get aliases via IDENTIFIED_AS
                alias_result = session.run(
                    "MATCH (n)-[r:IDENTIFIED_AS]->(n) "
                    "WHERE elementId(n) = $eid AND r.surface_form IS NOT NULL "
                    "RETURN r.surface_form AS sf",
                    eid=eid,
                )
                aliases = [r["sf"] for r in alias_result if r["sf"].lower() != name.lower()]
                entities.append({
                    "name": name,
                    "type": type_name,
                    "aliases": aliases,
                })
    return entities


# --- ER scoring ---


def _score_er_global(er_ground_truth: dict, graph_entities: list[dict]) -> dict:
    """Score ER against the global section of er_ground_truth.

    Returns {node_count_expected, node_count_actual, node_count_accuracy,
             merge_recall, merge_total, merge_correct,
             false_merge_rate, false_merge_count, false_merge_total}.
    """
    expected = er_ground_truth.get("global", [])
    if not expected:
        return {}

    # --- Node count ---
    node_count_expected = len(expected)
    node_count_actual = len(graph_entities)

    # --- Merge recall ---
    # For each canonical entity, check if all its surface forms resolve
    # to a single graph node (either as the node's name or as an alias).
    # Build graph lookup: lowered surface form → node name
    graph_lookup: dict[str, str] = {}
    for ent in graph_entities:
        canonical = ent["name"].lower()
        graph_lookup[canonical] = ent["name"]
        for alias in ent.get("aliases", []):
            graph_lookup[alias.lower()] = ent["name"]

    merge_total = 0
    merge_correct = 0
    for exp in expected:
        surface_forms = exp.get("surface_forms", [])
        if len(surface_forms) <= 1:
            continue
        merge_total += 1
        # All surface forms should map to the same graph node
        resolved_nodes = set()
        for sf in surface_forms:
            node = graph_lookup.get(sf.lower())
            if node:
                resolved_nodes.add(node.lower())
        if len(resolved_nodes) == 1:
            merge_correct += 1

    merge_recall = merge_correct / merge_total if merge_total > 0 else 1.0

    # --- False merge rate ---
    # For each graph node, check that all surface forms resolving to it
    # belong to the same canonical entity.
    # Build reverse: graph node name → set of canonical entities it should belong to
    sf_to_canonical: dict[str, str] = {}
    for exp in expected:
        canonical = exp["canonical_name"].lower()
        for sf in exp.get("surface_forms", []):
            sf_to_canonical[sf.lower()] = canonical

    false_merge_count = 0
    false_merge_total = 0
    for ent in graph_entities:
        all_forms = [ent["name"].lower()] + [a.lower() for a in ent.get("aliases", [])]
        canonicals_for_node = set()
        for form in all_forms:
            c = sf_to_canonical.get(form)
            if c:
                canonicals_for_node.add(c)
        if len(canonicals_for_node) > 0:
            false_merge_total += 1
            if len(canonicals_for_node) > 1:
                false_merge_count += 1

    false_merge_rate = false_merge_count / false_merge_total if false_merge_total > 0 else 0.0

    return {
        "node_count_expected": node_count_expected,
        "node_count_actual": node_count_actual,
        "node_count_accuracy": 1.0 - abs(node_count_expected - node_count_actual) / max(node_count_expected, 1),
        "merge_recall": merge_recall,
        "merge_total": merge_total,
        "merge_correct": merge_correct,
        "false_merge_rate": false_merge_rate,
        "false_merge_count": false_merge_count,
        "false_merge_total": false_merge_total,
    }


def _score_er_timeslice(
    timeslice: dict, graph_entities: list[dict]
) -> dict:
    """Score ER for a single timeslice using the same logic as global."""
    # Reuse global scoring by wrapping the timeslice entities as a "global" list
    pseudo_gt = {"global": timeslice.get("entities", [])}
    return _score_er_global(pseudo_gt, graph_entities)


# --- Report ---


def _verbose_er_timeslice(timeslice: dict, graph_entities: list[dict]) -> None:
    """Print surface-form-level diagnostics for a timeslice."""
    # Build graph lookup: lowered surface form → node name
    graph_lookup: dict[str, str] = {}
    for ent in graph_entities:
        canonical = ent["name"].lower()
        graph_lookup[canonical] = ent["name"]
        for alias in ent.get("aliases", []):
            graph_lookup[alias.lower()] = ent["name"]

    for exp in timeslice.get("entities", []):
        canonical = exp["canonical_name"]
        surface_forms = exp.get("surface_forms", [])
        print(f"    {canonical}:")
        for sf in surface_forms:
            resolved_to = graph_lookup.get(sf.lower())
            if resolved_to is None:
                print(f"      \u2717 \"{sf}\" \u2192 not found in graph")
            elif resolved_to.lower() == canonical.lower():
                print(f"      \u2713 \"{sf}\" \u2192 {resolved_to}")
            else:
                print(f"      \u2717 \"{sf}\" \u2192 {resolved_to} (expected {canonical})")


def _print_er_report(global_scores: dict, timeslice_scores: list[tuple[str, dict]] | None = None):
    """Print ER scoring results."""
    print()
    print("=" * 50)
    print("Entity Resolution — Global")
    print("=" * 50)
    print(f"  Node count:    {global_scores['node_count_expected']} expected, "
          f"{global_scores['node_count_actual']} actual "
          f"({global_scores['node_count_accuracy']:.0%})")
    print(f"  Merge recall:  {global_scores['merge_correct']}/{global_scores['merge_total']} "
          f"({global_scores['merge_recall']:.0%})")
    print(f"  False merges:  {global_scores['false_merge_count']}/{global_scores['false_merge_total']} "
          f"({global_scores['false_merge_rate']:.0%})")

    if timeslice_scores:
        print()
        print("-" * 50)
        print("Entity Resolution — Per Record")
        print("-" * 50)
        for record_key, scores in timeslice_scores:
            if not scores:
                continue
            print(f"  {record_key}:")
            print(f"    nodes: {scores['node_count_expected']} expected, {scores['node_count_actual']} actual")
            if scores["merge_total"] > 0:
                print(f"    merges: {scores['merge_correct']}/{scores['merge_total']}")
            if scores["false_merge_count"] > 0:
                print(f"    false merges: {scores['false_merge_count']}")
    print()


# --- Main pipeline ---


def run_er_eval(dataset_path: str, *, verbose: bool = False) -> dict:
    """Run ER evaluation. Returns scores dict."""
    init_db()
    from pearscarf.storage import store

    config = _load_dataset_config(dataset_path)
    data_map = config.get("data_map", {})
    version = config.get("version", "unknown")
    data_dir = os.path.join(dataset_path, "data")

    # Load ER ground truth
    er_gt_file = config.get("ground_truth", {}).get("entity_resolution")
    if not er_gt_file:
        raise SystemExit("No entity_resolution ground truth configured in dataset.yaml")
    er_gt_path = os.path.join(dataset_path, er_gt_file)
    if not os.path.isfile(er_gt_path):
        raise SystemExit(f"ER ground truth not found: {er_gt_path}")
    with open(er_gt_path) as fh:
        er_ground_truth = json.load(fh)

    print(f"PearScarf v{pearscarf_version} — ER eval against dataset v{version}")
    print(f"Model: {EXTRACTION_MODEL}  Temperature: {EXTRACTION_TEMPERATURE}  Max tokens: {EXTRACTION_MAX_TOKENS}")
    print()

    # Require clean graph
    if not _graph_is_empty():
        raise SystemExit(
            "Neo4j graph is not empty — eval requires a clean graph.\n"
            "Run `psc erase-all` and retry."
        )

    # Load expert connects
    _ensure_expert_connects()

    # Ingest seed
    seed_path = os.path.join(dataset_path, "seed.md")
    if os.path.isfile(seed_path):
        with open(seed_path) as fh:
            seed_content = fh.read()
        rid = store.save_ingest(source="eval_runner", raw=seed_content)
        print(f"Seed ingested as {rid}")

    # Determine record order
    sequence = _load_sequence(dataset_path)

    if sequence is None:
        # Fallback: walk all folders, sorted
        sequence = []
        for folder_name in sorted(data_map.keys()):
            folder_path = os.path.join(data_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            for fname in sorted(os.listdir(folder_path)):
                if fname.endswith(".json"):
                    sequence.append(fname.rsplit(".", 1)[0])

    print(f"Ingesting {len(sequence)} record(s)...")

    # Ingest in sequence order
    timeslices = er_ground_truth.get("timeslices", [])
    timeslice_by_record: dict[str, dict] = {
        ts["record"]: ts for ts in timeslices
    }
    timeslice_scores: list[tuple[str, dict]] = []

    for record_key in sequence:
        resolved = _resolve_record_file(record_key, data_dir, data_map)
        if not resolved:
            print(f"  {record_key}: file not found — skipped")
            continue
        file_path, record_type = resolved
        rid = _ingest_file(file_path, record_type)
        if rid:
            print(f"  {record_key}: ingested as {rid}")
        else:
            print(f"  {record_key}: skipped (duplicate or error)")
            continue

        # Wait for this record to be indexed before scoring timeslice
        _wait_for_indexer()

        # Score timeslice if ground truth exists for this record
        if record_key in timeslice_by_record:
            graph_entities = _get_all_graph_entities()
            ts = timeslice_by_record[record_key]
            ts_scores = _score_er_timeslice(ts, graph_entities)
            timeslice_scores.append((record_key, ts_scores))
            if verbose:
                _verbose_er_timeslice(ts, graph_entities)

    print()

    # Final global scoring
    graph_entities = _get_all_graph_entities()
    global_scores = _score_er_global(er_ground_truth, graph_entities)

    _print_er_report(global_scores, timeslice_scores if timeslice_scores else None)

    if verbose:
        print("-" * 50)
        print("Entity Resolution — Global Diagnostics")
        print("-" * 50)
        _verbose_er_timeslice({"entities": er_ground_truth.get("global", [])}, graph_entities)
        print()

    return {
        "global": global_scores,
        "timeslices": timeslice_scores,
    }


def run_graph_eval(dataset_path: str, *, verbose: bool = False) -> None:
    """Run all available eval types for a dataset."""
    config = _load_dataset_config(dataset_path)
    gt_config = config.get("ground_truth", {})

    if gt_config.get("entity_resolution"):
        run_er_eval(dataset_path)
    else:
        print("No eval types configured in dataset.yaml")
