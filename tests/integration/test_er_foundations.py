"""ER foundation integration tests.

Covers the graph-layer primitives that entity resolution builds on:
entity create/find, alias resolution (via IDENTIFIED_AS), fact-edge
writes and dedup-merge, and the read-side `context_query.find_entity` /
`get_facts` bundles. No LLM in scope — these tests guard the storage
foundation, not the extractor agent.

Requires the isolated test stack — `scripts/test-stack.sh up` and
`pytest --integration`.
"""

from __future__ import annotations

import pytest

from pearscarf.query import context_query
from pearscarf.storage import graph

pytestmark = pytest.mark.integration


def test_create_and_find_entity_by_name(clean_db) -> None:
    """A created entity is findable via direct graph lookup and the read layer."""
    eid = graph.create_entity("person", "Alice", {})
    assert eid

    direct = graph.find_entity("person", "Alice")
    assert direct is not None
    assert direct["name"] == "Alice"

    found = context_query.find_entity("Alice")
    assert len(found) == 1
    assert found[0]["id"] == eid
    assert found[0]["name"] == "Alice"


def test_find_entity_unknown_name_returns_empty(clean_db) -> None:
    """Looking up a name with no matching entity returns an empty list."""
    graph.create_entity("person", "Alice", {})
    assert context_query.find_entity("Bob") == []


def test_alias_resolution_via_identified_as(clean_db) -> None:
    """An IDENTIFIED_AS alias edge makes the canonical entity findable by alias."""
    eid = graph.create_entity("person", "Alice", {})
    graph.create_identified_as_edge(
        eid, "Al", source_record="rec_001", source_type="test", confidence="stated"
    )

    matches = graph.find_by_identified_as("Al")
    assert len(matches) == 1
    assert matches[0]["id"] == eid


def test_create_fact_edge_and_read_via_context_query(clean_db) -> None:
    """A fact edge written via graph.create_fact_edge is readable via context_query.get_facts."""
    alice = graph.create_entity("person", "Alice", {})
    acme = graph.create_entity("company", "Acme Corp", {})

    edge_id = graph.create_fact_edge(
        from_node_id=alice,
        to_node_id=acme,
        edge_label="AFFILIATED",
        fact_type="employee",
        fact="Alice works at Acme Corp.",
        confidence="stated",
        source_record="rec_001",
        source_type="email",
        source_at="2026-05-12T00:00:00+00:00",
    )
    assert edge_id

    facts = context_query.get_facts(alice)
    assert len(facts) == 1
    assert facts[0]["fact"] == "Alice works at Acme Corp."
    assert facts[0]["edge_label"] == "AFFILIATED"
    assert facts[0]["fact_type"] == "employee"


def test_find_exact_dup_edge_idempotency(clean_db) -> None:
    """find_exact_dup_edge spots a re-write from the SAME source_record (idempotency hook).

    The dedup contract is "did this record already write this fact?" — not
    "does any other record have this fact?". A different record writing the
    same fact is a fresh write (no dup), and merging happens via
    `append_source_record` when extraction explicitly chooses to merge.
    """
    alice = graph.create_entity("person", "Alice", {})
    acme = graph.create_entity("company", "Acme Corp", {})

    edge_id = graph.create_fact_edge(
        from_node_id=alice,
        to_node_id=acme,
        edge_label="AFFILIATED",
        fact_type="employee",
        fact="Alice works at Acme Corp.",
        confidence="stated",
        source_record="rec_001",
        source_type="email",
        source_at="2026-05-12T00:00:00+00:00",
    )

    same_record = graph.find_exact_dup_edge(
        alice, "AFFILIATED", "employee", acme, "rec_001", "Alice works at Acme Corp."
    )
    assert same_record == edge_id

    different_record = graph.find_exact_dup_edge(
        alice, "AFFILIATED", "employee", acme, "rec_002", "Alice works at Acme Corp."
    )
    assert different_record is None

    # Explicit merge via append_source_record adds rec_002 to the existing edge.
    graph.append_source_record(edge_id, "rec_002", confidence="inferred")
    with graph.get_session() as session:
        row = session.run(
            "MATCH ()-[r]->() WHERE elementId(r) = $rid RETURN r.source_record_ids AS ids",
            rid=edge_id,
        ).single()
    assert row is not None
    assert "rec_001" in row["ids"]
    assert "rec_002" in row["ids"]
    # Still one edge — no second one created.
    facts = context_query.get_facts(alice)
    assert len(facts) == 1
