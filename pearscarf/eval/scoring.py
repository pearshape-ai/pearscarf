"""Evaluation scoring functions.

Pure functions for matching extracted output against ground truth
and computing eval metrics. No I/O.
"""

from __future__ import annotations


def match_entities(
    extracted: list[dict],
    expected: list[dict],
) -> tuple[int, int, int]:
    """Match extracted entities against expected ground truth.

    Returns (matched, total_extracted, total_expected).

    Match criteria: exact name match (case-insensitive) OR any alias in
    expected entity matches extracted entity name. Type must also match.
    Each expected entity matches at most once.
    """
    # Build lookup: lowered name/alias -> index in expected list
    alias_map: dict[str, int] = {}
    for i, exp in enumerate(expected):
        canonical = exp.get("name", "").lower()
        if canonical:
            alias_map[canonical] = i
        for alias in exp.get("aliases", []):
            alias_map[alias.lower()] = i

    matched_indices: set[int] = set()
    for ext in extracted:
        ext_name = ext.get("name", "").lower()
        ext_type = ext.get("type", "").lower()
        if not ext_name:
            continue
        idx = alias_map.get(ext_name)
        if idx is not None and idx not in matched_indices:
            exp = expected[idx]
            if exp.get("type", "").lower() == ext_type:
                matched_indices.add(idx)

    return len(matched_indices), len(extracted), len(expected)


def match_facts(
    extracted: list[dict],
    expected: list[dict],
) -> tuple[int, int, int]:
    """Match extracted facts against expected ground truth.

    Returns (matched, total_extracted, total_expected).

    Match criteria: edge_label equal, fact_type equal, from_entity matches
    (case-insensitive), to_entity matches (case-insensitive, both None
    counts as match). Each expected fact matches at most once.
    """
    matched_indices: set[int] = set()
    for ext in extracted:
        ext_label = ext.get("edge_label", "").upper()
        ext_ft = ext.get("fact_type", "").lower()
        ext_from = (ext.get("from_entity") or "").lower()
        ext_to = (ext.get("to_entity") or "").lower() or None

        for i, exp in enumerate(expected):
            if i in matched_indices:
                continue
            exp_label = exp.get("edge_label", "").upper()
            exp_ft = exp.get("fact_type", "").lower()
            exp_from = (exp.get("from_entity") or "").lower()
            exp_to = (exp.get("to_entity") or "").lower() or None

            if (
                ext_label == exp_label
                and ext_ft == exp_ft
                and ext_from == exp_from
                and ext_to == exp_to
            ):
                matched_indices.add(i)
                break

    return len(matched_indices), len(extracted), len(expected)


def precision(matched: int, total_extracted: int) -> float:
    """matched / total_extracted. Returns 1.0 if total_extracted == 0."""
    if total_extracted == 0:
        return 1.0
    return matched / total_extracted


def recall(matched: int, total_expected: int) -> float:
    """matched / total_expected. Returns 1.0 if total_expected == 0."""
    if total_expected == 0:
        return 1.0
    return matched / total_expected


def f1(prec: float, rec: float) -> float:
    """Harmonic mean of precision and recall. Returns 0.0 if both are 0."""
    if prec + rec == 0:
        return 0.0
    return 2 * prec * rec / (prec + rec)


def noise_rejection_rate(per_record_results: list[dict]) -> float | None:
    """Fraction of noise records that produced zero extractions.

    Returns None if no noise records exist in the dataset.
    """
    noise_records = [r for r in per_record_results if r.get("is_noise")]
    if not noise_records:
        return None
    correct = sum(1 for r in noise_records if r.get("noise_correctly_empty"))
    return correct / len(noise_records)


def temporal_accuracy(
    temporal_assertions: list[dict],
    extracted_facts_by_record: dict[str, list[dict]],
) -> float | None:
    """Check temporal correctness of extracted facts against expected edges.

    Supports two formats:
    - New nested: {"record_id", "expected_edges": [{"source_record", "edge_label",
      "fact_type", "from_entity", "stale", "valid_until"}]}
    - Legacy flat: {"record_id", "fact_category", "from_entity", "valid_at"}

    Returns correct / total, or None if no assertions.
    """
    if not temporal_assertions:
        return None

    correct = 0
    total = 0

    for assertion in temporal_assertions:
        expected_edges = assertion.get("expected_edges")

        if expected_edges:
            # New nested format
            for edge in expected_edges:
                total += 1
                sr = edge.get("source_record", assertion.get("record_id", ""))
                facts = extracted_facts_by_record.get(sr, [])
                label = edge.get("edge_label", "").upper()
                ft = edge.get("fact_type", "").lower()
                from_e = edge.get("from_entity", "").lower()

                for fact in facts:
                    if (
                        fact.get("edge_label", "").upper() == label
                        and fact.get("fact_type", "").lower() == ft
                        and (fact.get("from_entity") or "").lower() == from_e
                    ):
                        # Check stale
                        stale_ok = fact.get("stale", False) == edge.get("stale", False)
                        # Check valid_until
                        exp_vu = (edge.get("valid_until") or "")[:10]
                        ext_vu = (fact.get("valid_until") or "")[:10]
                        vu_ok = exp_vu == ext_vu if exp_vu else True
                        if stale_ok and vu_ok:
                            correct += 1
                        break
        else:
            # Legacy flat format
            total += 1
            record_id = assertion["record_id"]
            facts = extracted_facts_by_record.get(record_id, [])
            cat = assertion.get("fact_category", "").upper()
            from_e = assertion.get("from_entity", "").lower()

            for fact in facts:
                if (
                    fact.get("edge_label", "").upper() == cat
                    and (fact.get("from_entity") or "").lower() == from_e
                ):
                    extracted_valid = (fact.get("source_at") or "")[:10]
                    expected_valid = (assertion.get("valid_at") or "")[:10]
                    if extracted_valid == expected_valid:
                        correct += 1
                    break

    return correct / total if total > 0 else None


def score_record(extracted: dict, expected: dict) -> dict:
    """Score a single record's extraction against ground truth.

    extracted: {"entities": [...], "facts": [...]} — LLM output
    expected: {"expected_entities": [...], "expected_facts": [...],
               "is_noise": bool}
    """
    ext_entities = extracted.get("entities", [])
    ext_facts = extracted.get("facts", [])
    exp_entities = expected.get("expected_entities", [])
    exp_facts = expected.get("expected_facts", [])
    is_noise = expected.get("is_noise", False)

    ent_matched, ent_extracted, ent_expected = match_entities(ext_entities, exp_entities)
    fact_matched, fact_extracted, fact_expected = match_facts(ext_facts, exp_facts)

    ent_prec = precision(ent_matched, ent_extracted)
    ent_rec = recall(ent_matched, ent_expected)
    fact_prec = precision(fact_matched, fact_extracted)
    fact_rec = recall(fact_matched, fact_expected)

    extracted_empty = len(ext_entities) == 0 and len(ext_facts) == 0

    result = {
        "entity_precision": ent_prec,
        "entity_recall": ent_rec,
        "fact_precision": fact_prec,
        "fact_recall": fact_rec,
        "is_noise": is_noise,
        "noise_correctly_empty": is_noise and extracted_empty,
        "entity_matched": ent_matched,
        "entity_extracted": ent_extracted,
        "entity_expected": ent_expected,
        "fact_matched": fact_matched,
        "fact_extracted": fact_extracted,
        "fact_expected": fact_expected,
    }

    # Per-label fact counts
    for label in ("AFFILIATED", "ASSERTED", "TRANSITIONED"):
        label_ext = [f for f in ext_facts if f.get("edge_label", "").upper() == label]
        label_exp = [f for f in exp_facts if f.get("edge_label", "").upper() == label]
        lm, le, lex = match_facts(label_ext, label_exp)
        result[f"{label.lower()}_matched"] = lm
        result[f"{label.lower()}_extracted"] = le
        result[f"{label.lower()}_expected"] = lex

    # Confidence mismatch warnings
    confidence_warnings: list[str] = []
    for ext in ext_facts:
        for exp in exp_facts:
            if (
                ext.get("edge_label", "").upper() == exp.get("edge_label", "").upper()
                and ext.get("fact_type", "").lower() == exp.get("fact_type", "").lower()
                and (ext.get("from_entity") or "").lower() == (exp.get("from_entity") or "").lower()
                and (ext.get("to_entity") or "").lower() == (exp.get("to_entity") or "").lower()
                and ext.get("confidence", "") != exp.get("confidence", "")
            ):
                confidence_warnings.append(
                    f"{ext.get('from_entity', '?')}: extracted={ext.get('confidence', '?')} "
                    f"expected={exp.get('confidence', '?')}"
                )
    result["confidence_warnings"] = confidence_warnings

    return result
