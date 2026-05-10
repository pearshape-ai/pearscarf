"""Tests for `pearscarf.eval.scoring` — pure metric functions."""

from __future__ import annotations

from pearscarf.eval.scoring import (
    f1,
    match_entities,
    match_facts,
    noise_rejection_rate,
    precision,
    recall,
    score_record,
    temporal_accuracy,
)

# ---- precision / recall / f1 ----


def test_precision_zero_extracted_returns_one() -> None:
    assert precision(0, 0) == 1.0


def test_precision_basic() -> None:
    assert precision(3, 4) == 0.75


def test_recall_zero_expected_returns_one() -> None:
    assert recall(0, 0) == 1.0


def test_recall_basic() -> None:
    assert recall(3, 5) == 0.6


def test_f1_zero_when_both_zero() -> None:
    assert f1(0.0, 0.0) == 0.0


def test_f1_harmonic_mean() -> None:
    assert f1(0.5, 0.5) == 0.5
    assert abs(f1(1.0, 0.5) - 2 / 3) < 1e-9


# ---- match_entities ----


def test_match_entities_exact_name_with_type() -> None:
    extracted = [{"name": "Alice", "type": "person"}]
    expected = [{"name": "Alice", "type": "person"}]
    assert match_entities(extracted, expected) == (1, 1, 1)


def test_match_entities_alias_match() -> None:
    extracted = [{"name": "Al", "type": "person"}]
    expected = [{"name": "Alice", "type": "person", "aliases": ["Al"]}]
    assert match_entities(extracted, expected) == (1, 1, 1)


def test_match_entities_type_mismatch_does_not_count() -> None:
    extracted = [{"name": "Alice", "type": "company"}]
    expected = [{"name": "Alice", "type": "person"}]
    assert match_entities(extracted, expected) == (0, 1, 1)


def test_match_entities_each_expected_matches_at_most_once() -> None:
    extracted = [
        {"name": "Alice", "type": "person"},
        {"name": "Alice", "type": "person"},
    ]
    expected = [{"name": "Alice", "type": "person"}]
    matched, te, ex = match_entities(extracted, expected)
    assert matched == 1
    assert te == 2
    assert ex == 1


# ---- match_facts ----


def test_match_facts_full_match_with_to_entity() -> None:
    e = [
        {
            "edge_label": "AFFILIATED",
            "fact_type": "employee",
            "from_entity": "Alice",
            "to_entity": "Acme",
        }
    ]
    exp = [
        {
            "edge_label": "AFFILIATED",
            "fact_type": "employee",
            "from_entity": "Alice",
            "to_entity": "Acme",
        }
    ]
    assert match_facts(e, exp) == (1, 1, 1)


def test_match_facts_no_to_entity_match() -> None:
    e = [
        {
            "edge_label": "ASSERTED",
            "fact_type": "commitment",
            "from_entity": "Alice",
            "to_entity": None,
        }
    ]
    exp = [
        {
            "edge_label": "ASSERTED",
            "fact_type": "commitment",
            "from_entity": "Alice",
            "to_entity": None,
        }
    ]
    assert match_facts(e, exp) == (1, 1, 1)


def test_match_facts_label_mismatch() -> None:
    e = [
        {
            "edge_label": "AFFILIATED",
            "fact_type": "employee",
            "from_entity": "Alice",
            "to_entity": "Acme",
        }
    ]
    exp = [
        {
            "edge_label": "ASSERTED",
            "fact_type": "employee",
            "from_entity": "Alice",
            "to_entity": "Acme",
        }
    ]
    assert match_facts(e, exp) == (0, 1, 1)


# ---- noise_rejection_rate ----


def test_noise_rejection_rate_none_when_no_noise() -> None:
    assert noise_rejection_rate([{"is_noise": False}]) is None


def test_noise_rejection_rate_correct_count() -> None:
    results = [
        {"is_noise": True, "noise_correctly_empty": True},
        {"is_noise": True, "noise_correctly_empty": False},
        {"is_noise": True, "noise_correctly_empty": True},
        {"is_noise": False},
    ]
    assert noise_rejection_rate(results) == 2 / 3


# ---- temporal_accuracy ----


def test_temporal_accuracy_returns_none_for_empty() -> None:
    assert temporal_accuracy([], {}) is None


def test_temporal_accuracy_legacy_format() -> None:
    assertions = [
        {
            "record_id": "r1",
            "fact_category": "AFFILIATED",
            "from_entity": "Alice",
            "valid_at": "2026-01-15",
        }
    ]
    extracted = {
        "r1": [
            {"edge_label": "AFFILIATED", "from_entity": "Alice", "source_at": "2026-01-15T10:00"}
        ]
    }
    assert temporal_accuracy(assertions, extracted) == 1.0


def test_temporal_accuracy_nested_format_with_stale_check() -> None:
    assertions = [
        {
            "record_id": "r1",
            "expected_edges": [
                {
                    "edge_label": "TRANSITIONED",
                    "fact_type": "status_change",
                    "from_entity": "Alice",
                    "stale": True,
                    "valid_until": "2026-02-01",
                }
            ],
        }
    ]
    extracted = {
        "r1": [
            {
                "edge_label": "TRANSITIONED",
                "fact_type": "status_change",
                "from_entity": "Alice",
                "stale": True,
                "valid_until": "2026-02-01T00:00",
            }
        ]
    }
    assert temporal_accuracy(assertions, extracted) == 1.0


# ---- score_record ----


def test_score_record_returns_per_label_counts() -> None:
    extracted = {
        "entities": [{"name": "Alice", "type": "person"}],
        "facts": [
            {
                "edge_label": "AFFILIATED",
                "fact_type": "employee",
                "from_entity": "Alice",
                "to_entity": "Acme",
                "confidence": "stated",
            },
        ],
    }
    expected = {
        "expected_entities": [{"name": "Alice", "type": "person"}],
        "expected_facts": [
            {
                "edge_label": "AFFILIATED",
                "fact_type": "employee",
                "from_entity": "Alice",
                "to_entity": "Acme",
                "confidence": "stated",
            },
        ],
    }
    result = score_record(extracted, expected)
    assert result["entity_matched"] == 1
    assert result["fact_matched"] == 1
    assert result["affiliated_matched"] == 1
    assert result["asserted_matched"] == 0
    assert result["confidence_warnings"] == []


def test_score_record_flags_confidence_warnings() -> None:
    extracted = {
        "entities": [],
        "facts": [
            {
                "edge_label": "ASSERTED",
                "fact_type": "commitment",
                "from_entity": "A",
                "to_entity": "B",
                "confidence": "inferred",
            },
        ],
    }
    expected = {
        "expected_entities": [],
        "expected_facts": [
            {
                "edge_label": "ASSERTED",
                "fact_type": "commitment",
                "from_entity": "A",
                "to_entity": "B",
                "confidence": "stated",
            },
        ],
    }
    result = score_record(extracted, expected)
    assert result["confidence_warnings"]
    assert "inferred" in result["confidence_warnings"][0]


def test_score_record_noise_correctly_empty_only_when_noise_and_empty() -> None:
    res_relevant_empty = score_record(
        {"entities": [], "facts": []},
        {"expected_entities": [], "expected_facts": [], "is_noise": False},
    )
    res_noise_empty = score_record(
        {"entities": [], "facts": []},
        {"expected_entities": [], "expected_facts": [], "is_noise": True},
    )
    res_noise_nonempty = score_record(
        {"entities": [{"name": "x", "type": "person"}], "facts": []},
        {"expected_entities": [], "expected_facts": [], "is_noise": True},
    )
    assert res_relevant_empty["noise_correctly_empty"] is False
    assert res_noise_empty["noise_correctly_empty"] is True
    assert res_noise_nonempty["noise_correctly_empty"] is False
