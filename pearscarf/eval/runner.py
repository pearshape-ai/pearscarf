"""Eval runner — dataset-driven evaluation pipeline.

Usage:
    psc eval er --dataset <path>       # ER scoring only
    psc eval --dataset <path>          # all available eval types

Pipeline:
    1. Read dataset.yaml for config
    2. Read sequence.yaml — each entry has file path + record type
    3. Ingest records in sequence order
    4. Wait for extraction after each record
    5. Score against ground truth
    6. Print results
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
    """Load dataset.yaml."""
    cfg_path = os.path.join(dataset_path, "dataset.yaml")
    if not os.path.isfile(cfg_path):
        raise SystemExit(f"dataset.yaml not found in {dataset_path}")
    with open(cfg_path) as fh:
        return yaml.safe_load(fh) or {}


def _load_sequence(dataset_path: str, config: dict) -> list[dict]:
    """Load sequence from the file referenced in dataset.yaml.

    Each entry: {"file": "records/seed.md", "type": "seed"}
    """
    seq_file = config.get("sequence")
    if not seq_file:
        raise SystemExit("No sequence file configured in dataset.yaml")
    seq_path = os.path.join(dataset_path, seq_file)
    if not os.path.isfile(seq_path):
        raise SystemExit(f"Sequence file not found: {seq_path}")
    with open(seq_path) as fh:
        entries = yaml.safe_load(fh) or []
    if not isinstance(entries, list):
        raise SystemExit(f"Sequence file must be a list, got {type(entries).__name__}")
    return entries


# --- Ingestion helpers ---


def _ensure_expert_connects():
    """Load expert connects so ingest tools can delegate."""
    from pearscarf.bus import MessageBus
    from pearscarf.expert_context import build_context
    from pearscarf.registry import get_registry

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


def _ingest_record_file(dataset_path: str, file_rel: str, record_type: str) -> str | None:
    """Ingest a single file from the dataset. Returns record_id or None."""
    from pearscarf.registry import get_registry
    from pearscarf.storage import store

    file_path = os.path.join(dataset_path, file_rel)
    if not os.path.isfile(file_path):
        print(f"    Error: file not found: {file_rel}")
        return None

    # Seed records
    if record_type == "seed":
        with open(file_path) as fh:
            content = fh.read()
        return store.save_ingest(source="eval_runner", raw=content)

    # Expert records
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


def _pending_record_count() -> int:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM records "
            "WHERE indexed = FALSE AND classification = %s",
            (store.RELEVANT,),
        ).fetchone()
        return dict(row).get("c", 0) if row else 0


def _graph_is_empty() -> bool:
    stats = graph.graph_stats()
    return stats.get("total_entities", 0) == 0 and stats.get("day_nodes", 0) == 0


def _wait_for_extraction():
    """Block until all relevant records are indexed."""
    print("Waiting for extraction...")
    start = time.time()
    while True:
        pending = _pending_record_count()
        if pending == 0:
            print("Extraction finished.")
            break
        elapsed = int(time.time() - start)
        print(f"  {pending} record(s) remaining... ({elapsed}s)")
        time.sleep(2)


def _record_label(entry: dict) -> str:
    """Derive a short label from a sequence entry for display."""
    file_rel = entry.get("file", "")
    return os.path.splitext(os.path.basename(file_rel))[0]


# --- Graph queries ---


def _get_all_graph_facts() -> list[dict]:
    """Get all non-stale fact edges from Neo4j.

    Returns list of {"edge_label", "fact_type", "from_entity", "to_entity", "fact", "confidence", "valid_until"}.
    """
    facts = []
    with graph.get_session() as session:
        result = session.run(
            "MATCH (a)-[r]->(b) "
            "WHERE r.fact IS NOT NULL AND (r.stale IS NULL OR r.stale = false) "
            "AND NOT 'Day' IN labels(b) "
            "RETURN a.name AS from_name, type(r) AS edge_label, "
            "r.fact_type AS fact_type, r.fact AS fact, "
            "r.confidence AS confidence, r.valid_until AS valid_until, "
            "b.name AS to_name, labels(b) AS to_labels"
        )
        for record in result:
            to_name = record["to_name"] if record["to_labels"] and "Day" not in record["to_labels"] else None
            facts.append({
                "edge_label": record["edge_label"],
                "fact_type": record["fact_type"] or "",
                "from_entity": record["from_name"] or "",
                "to_entity": to_name,
                "fact": record["fact"] or "",
                "confidence": record["confidence"] or "",
                "valid_until": record["valid_until"],
            })

    # Also get single-entity facts (to Day nodes)
    with graph.get_session() as session:
        result = session.run(
            "MATCH (a)-[r]->(b:Day) "
            "WHERE r.fact IS NOT NULL AND (r.stale IS NULL OR r.stale = false) "
            "RETURN a.name AS from_name, type(r) AS edge_label, "
            "r.fact_type AS fact_type, r.fact AS fact, "
            "r.confidence AS confidence, r.valid_until AS valid_until"
        )
        for record in result:
            facts.append({
                "edge_label": record["edge_label"],
                "fact_type": record["fact_type"] or "",
                "from_entity": record["from_name"] or "",
                "to_entity": None,
                "fact": record["fact"] or "",
                "confidence": record["confidence"] or "",
                "valid_until": record["valid_until"],
            })

    return facts


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
    """Score ER against the global section of er_ground_truth."""
    expected = er_ground_truth.get("global", [])
    if not expected:
        return {}

    node_count_expected = len(expected)
    node_count_actual = len(graph_entities)

    # Build graph lookup: lowered surface form → node name
    graph_lookup: dict[str, str] = {}
    for ent in graph_entities:
        canonical = ent["name"].lower()
        graph_lookup[canonical] = ent["name"]
        for alias in ent.get("aliases", []):
            graph_lookup[alias.lower()] = ent["name"]

    # Merge recall (per surface form)
    sf_total = 0
    sf_correct = 0
    for exp in expected:
        canonical = exp["canonical_name"].lower()
        for sf in exp.get("surface_forms", []):
            sf_total += 1
            resolved_to = graph_lookup.get(sf.lower())
            if resolved_to and resolved_to.lower() == canonical:
                sf_correct += 1

    merge_recall = sf_correct / sf_total if sf_total > 0 else 1.0

    # Entity merge rate (all-or-nothing per entity)
    entity_merge_total = 0
    entity_merge_correct = 0
    for exp in expected:
        surface_forms = exp.get("surface_forms", [])
        if len(surface_forms) <= 1:
            continue
        entity_merge_total += 1
        canonical = exp["canonical_name"].lower()
        all_correct = all(
            graph_lookup.get(sf.lower(), "").lower() == canonical
            for sf in surface_forms
        )
        if all_correct:
            entity_merge_correct += 1

    entity_merge_rate = entity_merge_correct / entity_merge_total if entity_merge_total > 0 else 1.0

    # False merge rate
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
        "merge_recall_correct": sf_correct,
        "merge_recall_total": sf_total,
        "entity_merge_rate": entity_merge_rate,
        "entity_merge_correct": entity_merge_correct,
        "entity_merge_total": entity_merge_total,
        "false_merge_rate": false_merge_rate,
        "false_merge_count": false_merge_count,
        "false_merge_total": false_merge_total,
    }


def _score_er_timeslice(timeslice: dict, graph_entities: list[dict]) -> dict:
    """Score ER for a single timeslice."""
    pseudo_gt = {"global": timeslice.get("entities", [])}
    return _score_er_global(pseudo_gt, graph_entities)


# --- Report ---


def _format_verbose_er(timeslice: dict, graph_entities: list[dict]) -> str:
    """Format surface-form-level diagnostics for a timeslice."""
    graph_lookup: dict[str, str] = {}
    for ent in graph_entities:
        canonical = ent["name"].lower()
        graph_lookup[canonical] = ent["name"]
        for alias in ent.get("aliases", []):
            graph_lookup[alias.lower()] = ent["name"]

    lines: list[str] = []
    for exp in timeslice.get("entities", []):
        canonical = exp["canonical_name"]
        surface_forms = exp.get("surface_forms", [])
        lines.append(f"    {canonical}:")
        for sf in surface_forms:
            resolved_to = graph_lookup.get(sf.lower())
            if resolved_to is None:
                lines.append(f"      \u2717 \"{sf}\" \u2192 not found in graph")
            elif resolved_to.lower() == canonical.lower():
                lines.append(f"      \u2713 \"{sf}\" \u2192 {resolved_to}")
            else:
                lines.append(f"      \u2717 \"{sf}\" \u2192 {resolved_to} (expected {canonical})")
    return "\n".join(lines)


def _format_er_report(
    global_scores: dict,
    timeslice_scores: list[tuple[str, dict]] | None = None,
    verbose_sections: list[tuple[str, str]] | None = None,
    global_verbose: str | None = None,
) -> str:
    """Format the full ER report as a string."""
    lines: list[str] = []
    lines.append("")
    lines.append("=" * 50)
    lines.append("Entity Resolution — Global")
    lines.append("=" * 50)
    lines.append(f"  Node count:       {global_scores['node_count_expected']} expected, "
                 f"{global_scores['node_count_actual']} actual "
                 f"({global_scores['node_count_accuracy']:.0%})")
    lines.append(f"  Merge recall:     {global_scores['merge_recall_correct']}/{global_scores['merge_recall_total']} "
                 f"({global_scores['merge_recall']:.0%})")
    lines.append(f"  Entity merge rate:{global_scores['entity_merge_correct']}/{global_scores['entity_merge_total']} "
                 f"({global_scores['entity_merge_rate']:.0%})")
    lines.append(f"  False merges:     {global_scores['false_merge_count']}/{global_scores['false_merge_total']} "
                 f"({global_scores['false_merge_rate']:.0%})")

    if timeslice_scores:
        lines.append("")
        lines.append("-" * 50)
        lines.append("Entity Resolution — Per Record")
        lines.append("-" * 50)
        for record_key, scores in timeslice_scores:
            if not scores:
                continue
            lines.append(f"  {record_key}:")
            lines.append(f"    nodes: {scores['node_count_expected']} expected, {scores['node_count_actual']} actual")
            lines.append(f"    merge recall: {scores['merge_recall_correct']}/{scores['merge_recall_total']}")
            if scores["entity_merge_total"] > 0:
                lines.append(f"    entity merge rate: {scores['entity_merge_correct']}/{scores['entity_merge_total']}")
            if scores["false_merge_count"] > 0:
                lines.append(f"    false merges: {scores['false_merge_count']}")

    if global_verbose:
        lines.append("")
        lines.append("-" * 50)
        lines.append("Entity Resolution — Global Diagnostics")
        lines.append("-" * 50)
        lines.append(global_verbose)

    lines.append("")
    return "\n".join(lines)


# --- Main pipeline ---


def run_er_eval(dataset_path: str, *, verbose: bool = False, debug_dir: str | None = None) -> dict:
    """Run ER evaluation. Returns scores dict."""
    init_db()

    config = _load_dataset_config(dataset_path)
    version = config.get("version", "unknown")

    # Load sequence
    sequence = _load_sequence(dataset_path, config)

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

    # Start extraction
    from pearscarf.extraction import Extraction

    if debug_dir:
        from datetime import datetime, timezone
        dataset_name = os.path.basename(os.path.normpath(dataset_path))
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        run_name = f"{dataset_name}_v{version}_{timestamp}"
        debug_dir = os.path.join(debug_dir, run_name)
        os.makedirs(debug_dir, exist_ok=True)
        print(f"Debug output: {debug_dir}")

    extraction = Extraction(debug_dir=debug_dir)
    extraction.start()

    # Ingest in sequence order
    timeslices = er_ground_truth.get("timeslices", [])
    timeslice_by_record: dict[str, dict] = {
        ts["record"]: ts for ts in timeslices
    }
    timeslice_scores: list[tuple[str, dict]] = []

    print(f"Ingesting {len(sequence)} record(s)...")

    for entry in sequence:
        file_rel = entry.get("file", "")
        record_type = entry.get("type", "")
        label = _record_label(entry)

        rid = _ingest_record_file(dataset_path, file_rel, record_type)
        if rid:
            print(f"  {label}: ingested as {rid}")
        else:
            print(f"  {label}: skipped (duplicate or error)")
            continue

        # Wait for extraction
        _wait_for_extraction()

        # Score timeslice if ground truth exists for this record
        if label in timeslice_by_record:
            graph_entities = _get_all_graph_entities()
            ts = timeslice_by_record[label]
            ts_scores = _score_er_timeslice(ts, graph_entities)
            timeslice_scores.append((label, ts_scores))
            if verbose:
                print(_format_verbose_er(ts, graph_entities))

    print()

    # Final global scoring
    graph_entities = _get_all_graph_entities()
    global_scores = _score_er_global(er_ground_truth, graph_entities)

    # Collect token usage from extraction
    token_usage = extraction.token_usage
    extraction.stop()

    # Build verbose diagnostics
    global_verbose = None
    if verbose:
        global_verbose = _format_verbose_er({"entities": er_ground_truth.get("global", [])}, graph_entities)

    # Format and print report
    report = _format_er_report(
        global_scores,
        timeslice_scores if timeslice_scores else None,
        global_verbose=global_verbose,
    )
    print(report)

    # Print token summary
    if token_usage:
        total_in = sum(t["input"] for t in token_usage.values())
        total_out = sum(t["output"] for t in token_usage.values())
        print(f"Token usage: {total_in:,} input, {total_out:,} output ({total_in + total_out:,} total)")
        print()

    # Save to debug dir — always include full diagnostics in the file
    if debug_dir:
        full_verbose = _format_verbose_er({"entities": er_ground_truth.get("global", [])}, graph_entities)
        full_report = _format_er_report(
            global_scores,
            timeslice_scores if timeslice_scores else None,
            global_verbose=full_verbose,
        )
        results_path = os.path.join(debug_dir, "eval-results.md")
        with open(results_path, "w") as fh:
            fh.write(f"# ER Eval Results\n\n")
            fh.write(f"PearScarf v{pearscarf_version} — dataset v{version}\n")
            fh.write(f"Model: {EXTRACTION_MODEL}\n\n")
            fh.write(full_report)
            if token_usage:
                fh.write(f"\n## Token Usage\n\n")
                total_in = sum(t["input"] for t in token_usage.values())
                total_out = sum(t["output"] for t in token_usage.values())
                for rid, t in token_usage.items():
                    fh.write(f"  {rid}: {t['input']:,} in, {t['output']:,} out\n")
                fh.write(f"\n  Total: {total_in:,} input, {total_out:,} output ({total_in + total_out:,} total)\n")
        print(f"Results saved to {results_path}")

    return {
        "global": global_scores,
        "timeslices": timeslice_scores,
    }


# --- Facts scoring ---


def _score_facts(expected_facts: list[dict], graph_facts: list[dict], match_on: list[str]) -> dict:
    """Score extracted facts against ground truth.

    Matches on the fields listed in match_on. Returns precision, recall, F1, details.
    """
    def _key(f: dict) -> tuple:
        return tuple((f.get(k) or "").lower() for k in match_on)

    expected_keys = {_key(f): f for f in expected_facts}
    graph_keys = {_key(f): f for f in graph_facts}

    matched = set(expected_keys.keys()) & set(graph_keys.keys())
    missing = set(expected_keys.keys()) - set(graph_keys.keys())
    extra = set(graph_keys.keys()) - set(expected_keys.keys())

    total_expected = len(expected_facts)
    total_extracted = len(graph_facts)
    total_matched = len(matched)

    prec = total_matched / total_extracted if total_extracted > 0 else 1.0
    rec = total_matched / total_expected if total_expected > 0 else 1.0
    f1_score = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

    return {
        "precision": prec,
        "recall": rec,
        "f1": f1_score,
        "matched": total_matched,
        "expected": total_expected,
        "extracted": total_extracted,
        "missing": [expected_keys[k] for k in missing],
        "extra": [graph_keys[k] for k in extra],
    }


def _format_facts_report(scores: dict) -> str:
    """Format the facts scoring report."""
    lines = []
    lines.append("")
    lines.append("=" * 50)
    lines.append("Fact Extraction — Global")
    lines.append("=" * 50)
    lines.append(f"  Matched:    {scores['matched']}/{scores['expected']}")
    lines.append(f"  Precision:  {scores['precision']:.0%}")
    lines.append(f"  Recall:     {scores['recall']:.0%}")
    lines.append(f"  F1:         {scores['f1']:.0%}")
    lines.append(f"  Extracted:  {scores['extracted']} total in graph")

    if scores["missing"]:
        lines.append("")
        lines.append("  Missing (expected but not found):")
        for f in scores["missing"]:
            to = f" → {f['to_entity']}" if f.get('to_entity') else ""
            lines.append(f"    {f['edge_label']}/{f['fact_type']}: {f['from_entity']}{to}")

    if scores["extra"]:
        lines.append("")
        lines.append("  Extra (found but not expected):")
        for f in scores["extra"]:
            to = f" → {f['to_entity']}" if f.get('to_entity') else ""
            lines.append(f"    {f['edge_label']}/{f['fact_type']}: {f['from_entity']}{to}")
            if f.get("fact"):
                lines.append(f"      \"{f['fact'][:80]}\"")

    lines.append("")
    return "\n".join(lines)


def run_facts_eval(dataset_path: str, *, verbose: bool = False, debug_dir: str | None = None) -> dict:
    """Run facts evaluation. Returns scores dict."""
    init_db()

    config = _load_dataset_config(dataset_path)
    version = config.get("version", "unknown")
    sequence = _load_sequence(dataset_path, config)

    # Load fact ground truth
    facts_gt_file = config.get("ground_truth", {}).get("facts")
    if not facts_gt_file:
        raise SystemExit("No facts ground truth configured in dataset.yaml")
    facts_gt_path = os.path.join(dataset_path, facts_gt_file)
    if not os.path.isfile(facts_gt_path):
        raise SystemExit(f"Facts ground truth not found: {facts_gt_path}")
    with open(facts_gt_path) as fh:
        facts_gt = json.load(fh)

    expected_facts = facts_gt.get("expected_facts", [])
    match_on = facts_gt.get("match_on", ["edge_label", "fact_type", "from_entity", "to_entity"])

    print(f"PearScarf v{pearscarf_version} — facts eval against dataset v{version}")
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

    # Start extraction + curator
    from pearscarf.extraction import Extraction
    from pearscarf.curation import Curation

    if debug_dir:
        from datetime import datetime, timezone
        dataset_name = os.path.basename(os.path.normpath(dataset_path))
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        run_name = f"{dataset_name}_v{version}_{timestamp}"
        debug_dir = os.path.join(debug_dir, run_name)
        os.makedirs(debug_dir, exist_ok=True)
        print(f"Debug output: {debug_dir}")

    extraction = Extraction(debug_dir=debug_dir)
    extraction.start()

    curation = Curation()
    curation.start()

    # Ingest all records
    print(f"Ingesting {len(sequence)} record(s)...")
    for entry in sequence:
        file_rel = entry.get("file", "")
        record_type = entry.get("type", "")
        label = _record_label(entry)

        rid = _ingest_record_file(dataset_path, file_rel, record_type)
        if rid:
            print(f"  {label}: ingested as {rid}")
        else:
            print(f"  {label}: skipped (duplicate or error)")

    # Wait for extraction
    _wait_for_extraction()

    # Wait for curation to drain the queue
    print("Waiting for curation...")
    while True:
        with _get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM curator_queue").fetchone()
            count = dict(row).get("c", 0) if row else 0
        if count == 0:
            print("Curation finished.")
            break
        print(f"  {count} record(s) in queue...")
        time.sleep(2)

    # Collect token usage
    token_usage = extraction.token_usage
    extraction.stop()
    curation.stop()

    # Score facts
    graph_facts = _get_all_graph_facts()
    scores = _score_facts(expected_facts, graph_facts, match_on)

    report = _format_facts_report(scores)
    print(report)

    if token_usage:
        total_in = sum(t["input"] for t in token_usage.values())
        total_out = sum(t["output"] for t in token_usage.values())
        print(f"Token usage: {total_in:,} input, {total_out:,} output ({total_in + total_out:,} total)")
        print()

    # Save to debug dir
    if debug_dir:
        results_path = os.path.join(debug_dir, "eval-results.md")
        with open(results_path, "w") as fh:
            fh.write(f"# Facts Eval Results\n\n")
            fh.write(f"PearScarf v{pearscarf_version} — dataset v{version}\n")
            fh.write(f"Model: {EXTRACTION_MODEL}\n\n")
            fh.write(report)
        print(f"Results saved to {results_path}")

    return scores


def run_graph_eval(dataset_path: str, *, verbose: bool = False) -> None:
    """Run all available eval types for a dataset."""
    config = _load_dataset_config(dataset_path)
    gt_config = config.get("ground_truth", {})

    ran = False
    if gt_config.get("entity_resolution"):
        run_er_eval(dataset_path, verbose=verbose)
        ran = True
    if gt_config.get("facts"):
        run_facts_eval(dataset_path, verbose=verbose)
        ran = True
    if not ran:
        print("No eval types configured in dataset.yaml")
