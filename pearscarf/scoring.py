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

    Match criteria: category equal, from_entity matches (case-insensitive),
    to_entity matches (case-insensitive, both None counts as match).
    Each expected fact matches at most once.
    """
    matched_indices: set[int] = set()
    for ext in extracted:
        ext_cat = ext.get("category", "").upper()
        ext_from = (ext.get("from_entity") or "").lower()
        ext_to = (ext.get("to_entity") or "").lower() or None

        for i, exp in enumerate(expected):
            if i in matched_indices:
                continue
            exp_cat = exp.get("category", "").upper()
            exp_from = (exp.get("from_entity") or "").lower()
            exp_to = (exp.get("to_entity") or "").lower() or None

            if ext_cat == exp_cat and ext_from == exp_from and ext_to == exp_to:
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


def entity_resolution_accuracy(
    resolution_pairs: list[dict],
    extracted_entities_by_record: dict[str, list[dict]],
) -> float | None:
    """Check whether surface form variants resolve correctly.

    Each pair: {"surface_a": str, "surface_b": str, "record_a": str,
                "record_b": str, "expected_outcome": "merge"|"split"}

    For merge: correct if both surface forms resolve to the same canonical name.
    For split: correct if they resolve to different canonical names.

    Returns correct / total, or None if no pairs.
    """
    if not resolution_pairs:
        return None

    def _resolve(ref: str, record_id: str) -> str | None:
        """Find the canonical entity name that a surface ref resolved to."""
        entities = extracted_entities_by_record.get(record_id, [])
        ref_lower = ref.lower()
        for ent in entities:
            name = ent.get("name", "")
            if name.lower() == ref_lower:
                return name
            meta = ent.get("metadata", {})
            if meta.get("email", "").lower() == ref_lower:
                return name
        return None

    correct = 0
    for pair in resolution_pairs:
        name_a = _resolve(pair["surface_a"], pair["record_a"])
        name_b = _resolve(pair["surface_b"], pair["record_b"])
        if name_a is None or name_b is None:
            continue  # can't evaluate if entity wasn't extracted
        expected = pair["expected_outcome"]
        if expected == "merge" and name_a.lower() == name_b.lower():
            correct += 1
        elif expected == "split" and name_a.lower() != name_b.lower():
            correct += 1

    return correct / len(resolution_pairs)


def temporal_accuracy(
    temporal_assertions: list[dict],
    extracted_facts_by_record: dict[str, list[dict]],
) -> float | None:
    """Check whether extracted facts carry the correct valid_at.

    Each assertion: {"record_id": str, "fact_category": str,
                     "from_entity": str, "valid_at": str,
                     "invalid_at": str|None}

    Compares date portion (first 10 chars) of valid_at.
    Returns correct / total, or None if no assertions.
    """
    if not temporal_assertions:
        return None

    correct = 0
    for assertion in temporal_assertions:
        record_id = assertion["record_id"]
        facts = extracted_facts_by_record.get(record_id, [])
        cat = assertion["fact_category"].upper()
        from_e = assertion["from_entity"].lower()

        # Find matching extracted fact
        for fact in facts:
            if (
                fact.get("category", "").upper() == cat
                and (fact.get("from_entity") or "").lower() == from_e
            ):
                extracted_valid = (fact.get("valid_at") or "")[:10]
                expected_valid = (assertion.get("valid_at") or "")[:10]
                if extracted_valid == expected_valid:
                    correct += 1
                break

    return correct / len(temporal_assertions)


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

    return {
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
