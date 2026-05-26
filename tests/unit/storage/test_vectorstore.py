"""Tests for `pearscarf.storage.vectorstore` — qdrant wrapper."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pearscarf.storage import vectorstore


@pytest.fixture(autouse=True)
def _restore_singletons() -> None:
    yield
    vectorstore._client = None
    vectorstore._model = None


def _stub_embed() -> patch:
    return patch.object(vectorstore, "_embed", return_value=[0.0] * vectorstore.VECTOR_SIZE)


def test_record_id_to_uuid_is_deterministic() -> None:
    a = vectorstore._record_id_to_uuid("email_001")
    b = vectorstore._record_id_to_uuid("email_001")
    assert a == b
    assert a != vectorstore._record_id_to_uuid("email_002")


def test_add_record_upserts_with_payload(mock_qdrant_client: MagicMock) -> None:
    vectorstore._client = mock_qdrant_client
    with _stub_embed():
        vectorstore.add_record("email_001", "hello world", {"sender": "x@y.com", "empty": ""})

    mock_qdrant_client.upsert.assert_called_once()
    call = mock_qdrant_client.upsert.call_args
    assert call.kwargs["collection_name"] == vectorstore.COLLECTION_NAME
    point = call.kwargs["points"][0]
    payload = point.payload
    assert payload["record_id"] == "email_001"
    assert payload["content"] == "hello world"
    assert payload["sender"] == "x@y.com"
    assert "empty" not in payload  # falsy-stripped


def test_add_record_truncates_content_to_1000_chars(mock_qdrant_client: MagicMock) -> None:
    vectorstore._client = mock_qdrant_client
    long_content = "x" * 5000
    with _stub_embed():
        vectorstore.add_record("r1", long_content, {})
    point = mock_qdrant_client.upsert.call_args.kwargs["points"][0]
    assert len(point.payload["content"]) == 1000


def test_query_uses_query_points_and_shapes_response(mock_qdrant_client: MagicMock) -> None:
    vectorstore._client = mock_qdrant_client
    hit = SimpleNamespace(
        payload={"record_id": "r1", "content": "body", "sender": "a@b"},
        score=0.91,
    )
    mock_qdrant_client.query_points.return_value = SimpleNamespace(points=[hit])

    with _stub_embed():
        results = vectorstore.query("hello", n_results=3)

    mock_qdrant_client.query_points.assert_called_once()
    qkwargs = mock_qdrant_client.query_points.call_args.kwargs
    assert qkwargs["limit"] == 3
    assert results == [
        {
            "id": "r1",
            "content": "body",
            "metadata": {"sender": "a@b"},
            "score": 0.91,
        }
    ]


def test_add_fact_upserts_to_facts_collection(mock_qdrant_client: MagicMock) -> None:
    vectorstore._client = mock_qdrant_client
    with _stub_embed():
        vectorstore.add_fact(
            "5:abc:1",
            "Linus sourced 5 prospects",
            {"edge_label": "ASSERTED", "empty": ""},
        )

    mock_qdrant_client.upsert.assert_called_once()
    call = mock_qdrant_client.upsert.call_args
    assert call.kwargs["collection_name"] == vectorstore.FACTS_COLLECTION
    payload = call.kwargs["points"][0].payload
    assert payload["fact_id"] == "5:abc:1"
    assert payload["text"] == "Linus sourced 5 prospects"
    assert payload["edge_label"] == "ASSERTED"
    assert "empty" not in payload  # falsy-stripped


def test_add_fact_point_id_matches_record_uuid_scheme(mock_qdrant_client: MagicMock) -> None:
    vectorstore._client = mock_qdrant_client
    with _stub_embed():
        vectorstore.add_fact("5:abc:1", "x")
    point = mock_qdrant_client.upsert.call_args.kwargs["points"][0]
    assert point.id == vectorstore._record_id_to_uuid("5:abc:1")
