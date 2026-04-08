"""Execution harness — fast verification of the main pipeline branches.

Each test is independently runnable and isolated via fixtures in conftest.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from pearscarf import graph
from pearscarf.db import _get_conn

FIXTURES = Path(__file__).parent / "fixtures"


def _insert_issue(fixture_name: str) -> dict:
    """Insert an issue fixture into Postgres. Returns the record dict."""
    from psycopg.types.json import Jsonb

    data = json.loads((FIXTURES / fixture_name).read_text())
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO records (id, type, source, created_at, raw) "
            "VALUES (%s, 'issue', 'test', %s, %s)",
            (data["record_id"], data["linear_created_at"], data["description"]),
        )
        conn.execute(
            "INSERT INTO issues (record_id, linear_id, identifier, title, description, "
            "status, priority, assignee, project, labels, comments, "
            "linear_created_at, linear_updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                data["record_id"], data["linear_id"], data["identifier"],
                data["title"], data["description"], data["status"], data["priority"],
                data["assignee"], data["project"], Jsonb([]), Jsonb([]),
                data["linear_created_at"], data["linear_updated_at"],
            ),
        )
        conn.commit()
    return {"id": data["record_id"], "type": "issue", "source": "test"}


def _insert_ingest(fixture_name: str, record_id: str = "test_ingest_001") -> dict:
    """Insert a seed file as an ingest record. Returns the record dict."""
    raw = (FIXTURES / fixture_name).read_text()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO records (id, type, source, created_at, raw) "
            "VALUES (%s, 'ingest', 'test', now(), %s)",
            (record_id, raw),
        )
        conn.commit()
    return {"id": record_id, "type": "ingest", "source": "test", "raw": raw}


def _insert_email(fixture_name: str) -> dict:
    """Insert an email fixture into Postgres. Returns the record dict."""
    data = json.loads((FIXTURES / fixture_name).read_text())
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO records (id, type, source, created_at, raw) "
            "VALUES (%s, 'email', 'test', %s, %s)",
            (data["record_id"], data["received_at"], data["body"]),
        )
        conn.execute(
            "INSERT INTO emails "
            "(record_id, message_id, sender, recipient, subject, body, received_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                data["record_id"], data["message_id"], data["sender"],
                data["recipient"], data["subject"], data["body"], data["received_at"],
            ),
        )
        conn.commit()
    return {"id": data["record_id"], "type": "email", "source": "test"}


def test_graph_write(clean_graph):
    """A fact edge can be written and read back with all properties intact."""
    from_id = graph.create_entity("person", "David Kim", {"email": "david@pearventures.io"})
    to_id = graph.create_entity("company", "Pear Ventures", {"domain": "pearventures.io"})

    graph.create_fact_edge(
        from_node_id=from_id,
        to_node_id=to_id,
        edge_label="AFFILIATED",
        fact_type="employee",
        fact="David Kim works at Pear Ventures",
        confidence="stated",
        source_record="test_rec_001",
        source_type="test",
        source_at="2026-04-01T00:00:00Z",
    )

    edges = graph.get_edges_by_source_record("test_rec_001")
    assert len(edges) == 1

    edge = edges[0]
    assert edge["edge_label"] == "AFFILIATED"
    assert edge["fact_type"] == "employee"
    assert edge["fact"] == "David Kim works at Pear Ventures"
    assert edge["confidence"] == "stated"
    assert edge["source_at"] == "2026-04-01T00:00:00Z"
    assert edge["from_name"] == "David Kim"
    assert edge["to_name"] == "Pear Ventures"

    # source_records is the zipped [{record_id, confidence}] list
    assert any(
        sr["record_id"] == "test_rec_001" and sr["confidence"] == "stated"
        for sr in edge["source_records"]
    )


def test_entity_resolution(clean_graph):
    """A surface form alias resolves to the canonical entity via IDENTIFIED_AS."""
    canonical_id = graph.create_entity(
        "person", "James Whitfield", {"email": "j.whitfield@meridiansys.com"}
    )

    graph.create_identified_as_edge(
        entity_id=canonical_id,
        surface_form="Jim",
        source_record="test_rec_001",
        source_type="test",
        confidence="inferred",
        reasoning="Jim is short for James",
    )

    candidates = graph.find_entity_candidates("person", "Jim")

    assert len(candidates) >= 1
    assert any(c["name"] == "James Whitfield" for c in candidates)
    assert any(c["id"] == canonical_id for c in candidates)


VALID_EDGE_LABELS = {"AFFILIATED", "ASSERTED", "TRANSITIONED"}


def test_gmail_extraction(clean_graph, clean_records, mock_anthropic):
    """A fixture email record produces non-empty facts with valid edge labels."""
    from tests.fixtures import llm_responses
    from pearscarf.indexer import Indexer

    # Canned extraction: 2 entities + 2 facts
    llm_responses.RESPONSES["entity extraction system"] = json.dumps({
        "entities": [
            {"name": "James Whitfield", "type": "person",
             "metadata": {"email": "j.whitfield@meridiansys.com"}},
            {"name": "Meridian Systems", "type": "company",
             "metadata": {"domain": "meridiansys.com"}},
        ],
        "facts": [
            {"edge_label": "AFFILIATED", "fact_type": "employee",
             "from_entity": "James Whitfield", "to_entity": "Meridian Systems",
             "fact": "James Whitfield works at Meridian Systems",
             "confidence": "stated"},
            {"edge_label": "ASSERTED", "fact_type": "commitment",
             "from_entity": "James Whitfield", "to_entity": None,
             "fact": "James Whitfield will set up a technical review next Tuesday",
             "confidence": "stated"},
        ],
    })

    record = _insert_email("email.json")
    indexer = Indexer()
    indexer._process_record(record)

    edges = graph.get_edges_by_source_record(record["id"])
    assert len(edges) > 0, "expected non-empty facts from extraction"
    for edge in edges:
        assert edge["edge_label"] in VALID_EDGE_LABELS, (
            f"unexpected edge_label: {edge['edge_label']}"
        )


def test_linear_extraction(clean_graph, clean_records, mock_anthropic):
    """A fixture Linear issue produces non-empty facts with valid edge labels."""
    from tests.fixtures import llm_responses
    from pearscarf.indexer import Indexer

    llm_responses.RESPONSES["operational"] = json.dumps({
        "entities": [
            {"name": "David Kim", "type": "person", "metadata": {}},
            {"name": "Meridian API Integration", "type": "project", "metadata": {}},
        ],
        "facts": [
            {"edge_label": "AFFILIATED", "fact_type": "owner",
             "from_entity": "David Kim", "to_entity": "Meridian API Integration",
             "fact": "David Kim owns Meridian API Integration",
             "confidence": "stated"},
            {"edge_label": "ASSERTED", "fact_type": "blocker",
             "from_entity": "Meridian API Integration", "to_entity": None,
             "fact": "Meridian API Integration is blocked on credentials",
             "confidence": "stated"},
        ],
    })

    record = _insert_issue("issue.json")
    indexer = Indexer()
    indexer._process_record(record)

    edges = graph.get_edges_by_source_record(record["id"])
    assert len(edges) > 0, "expected non-empty facts from issue extraction"
    for edge in edges:
        assert edge["edge_label"] in VALID_EDGE_LABELS, (
            f"unexpected edge_label: {edge['edge_label']}"
        )


def test_ingest_seed(clean_graph, clean_records, mock_anthropic):
    """A seed file is processed end-to-end into the graph."""
    from tests.fixtures import llm_responses
    from pearscarf.indexer import Indexer

    llm_responses.RESPONSES["seed data files"] = json.dumps({
        "entities": [
            {"name": "David Kim", "type": "person",
             "metadata": {"email": "david@pearventures.io"}},
            {"name": "Pear Ventures", "type": "company",
             "metadata": {"domain": "pearventures.io"}},
            {"name": "Meridian API Integration", "type": "project", "metadata": {}},
        ],
        "facts": [
            {"edge_label": "AFFILIATED", "fact_type": "employee",
             "from_entity": "David Kim", "to_entity": "Pear Ventures",
             "fact": "David Kim works at Pear Ventures",
             "confidence": "stated"},
            {"edge_label": "AFFILIATED", "fact_type": "owner",
             "from_entity": "David Kim", "to_entity": "Meridian API Integration",
             "fact": "David Kim owns Meridian API Integration",
             "confidence": "stated"},
        ],
    })

    record = _insert_ingest("seed.md")
    indexer = Indexer()
    indexer._process_record(record)

    # Verify entities exist in graph
    assert graph.find_entity("person", "David Kim") is not None
    assert graph.find_entity("company", "Pear Ventures") is not None
    assert graph.find_entity("project", "Meridian API Integration") is not None

    # Verify facts written
    edges = graph.get_edges_by_source_record(record["id"])
    assert len(edges) == 2
    assert all(e["edge_label"] == "AFFILIATED" for e in edges)


def test_curator(clean_graph, clean_records, mock_anthropic):
    """AFFILIATED and ASSERTED facts both pass through the curator without error."""
    from pearscarf.curator import Curator

    # Pre-create entities
    david_id = graph.create_entity("person", "David Kim", {"email": "david@pearventures.io"})
    pear_id = graph.create_entity("company", "Pear Ventures", {"domain": "pearventures.io"})

    # AFFILIATED edge
    graph.create_fact_edge(
        from_node_id=david_id,
        to_node_id=pear_id,
        edge_label="AFFILIATED",
        fact_type="employee",
        fact="David Kim works at Pear Ventures",
        confidence="stated",
        source_record="test_curator_001",
        source_type="test",
        source_at="2026-04-01T00:00:00Z",
    )

    # ASSERTED edge
    graph.create_fact_edge(
        from_node_id=david_id,
        to_node_id=pear_id,
        edge_label="ASSERTED",
        fact_type="commitment",
        fact="David committed to ship the integration",
        confidence="stated",
        source_record="test_curator_001",
        source_type="test",
        source_at="2026-04-01T00:00:00Z",
    )

    # Run curator on this record — should complete without raising
    curator = Curator()
    curator._process("test_curator_001")

    # Edges should still exist (no judge call needed for single-edge slots)
    edges = graph.get_edges_by_source_record("test_curator_001")
    assert len(edges) == 2
    labels = {e["edge_label"] for e in edges}
    assert labels == {"AFFILIATED", "ASSERTED"}
