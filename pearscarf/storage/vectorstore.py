"""Vector storage layer — Qdrant wrapper.

Lazy-initialized. The Qdrant client and sentence-transformers model
only load on first use, so commands that don't need vector search stay fast.
"""

from __future__ import annotations

import uuid

from pearscarf.config import QDRANT_URL

_client = None
_model = None

COLLECTION_NAME = "records"
FACTS_COLLECTION = "facts"
VECTOR_SIZE = 384  # all-MiniLM-L6-v2 output dimension


def _record_id_to_uuid(record_id: str) -> str:
    """Deterministic UUID from a string record ID (e.g. 'email_001')."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, record_id))


def _get_client():
    """Lazy-init Qdrant client and ensure collections exist."""
    global _client
    if _client is None:
        from qdrant_client import QdrantClient

        _client = QdrantClient(url=QDRANT_URL)
        _ensure_collection(COLLECTION_NAME)
        _ensure_collection(FACTS_COLLECTION)
    return _client


def _get_model():
    """Lazy-init sentence-transformers model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _ensure_collection(name: str) -> None:
    """Create the given collection if it doesn't exist."""
    from qdrant_client.models import Distance, VectorParams

    assert _client is not None  # caller (`_get_client`) initializes before calling
    collections = [c.name for c in _client.get_collections().collections]
    if name not in collections:
        _client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


def _embed(text: str) -> list[float]:
    """Embed text using sentence-transformers."""
    model = _get_model()
    return model.encode(text).tolist()


def add_record(record_id: str, content: str, metadata: dict) -> None:
    """Add or update a record's embedding in Qdrant."""
    from qdrant_client.models import PointStruct

    client = _get_client()
    vector = _embed(content)

    payload = {
        "record_id": record_id,
        "content": content[:1000],
        **{k: v for k, v in metadata.items() if v},
    }

    point_id = _record_id_to_uuid(record_id)
    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[PointStruct(id=point_id, vector=vector, payload=payload)],
    )


def add_fact(fact_id: str, text: str, payload: dict | None = None) -> None:
    """Add or update a fact's embedding in the facts collection.

    `fact_id` is the graph edge's elementId. The Qdrant point id is a
    deterministic UUID of it, so re-adds upsert in place and the recall path can
    map a vector hit back to its edge. Written once per new fact edge at
    extraction time; stale facts are left in place (filtered at the recall hop).
    """
    from qdrant_client.models import PointStruct

    client = _get_client()
    vector = _embed(text)

    body = {
        "fact_id": fact_id,
        "text": text[:1000],
        **{k: v for k, v in (payload or {}).items() if v},
    }
    client.upsert(
        collection_name=FACTS_COLLECTION,
        points=[PointStruct(id=_record_id_to_uuid(fact_id), vector=vector, payload=body)],
    )


def query(
    query_text: str,
    n_results: int = 5,
    where: dict | None = None,
) -> list[dict]:
    """Query Qdrant for similar records."""
    client = _get_client()
    vector = _embed(query_text)

    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=n_results,
    )

    return [
        {
            "id": hit.payload.get("record_id", ""),
            "content": hit.payload.get("content", ""),
            "metadata": {k: v for k, v in hit.payload.items() if k not in ("record_id", "content")},
            "score": hit.score,
        }
        for hit in response.points
    ]


def search_facts(query_text: str, n_results: int = 20) -> list[dict]:
    """Semantic search over the facts collection.

    Returns hits as `{fact_id, text, edge_label, fact_type, source_record, score}`.
    `fact_id` is the graph edge's elementId — the recall path hydrates these
    against Neo4j (dropping stale, attaching entities), so this is just the
    fuzzy entry point, not the source of truth.
    """
    client = _get_client()
    vector = _embed(query_text)

    response = client.query_points(
        collection_name=FACTS_COLLECTION,
        query=vector,
        limit=n_results,
    )

    return [
        {
            "fact_id": hit.payload.get("fact_id", ""),
            "text": hit.payload.get("text", ""),
            "edge_label": hit.payload.get("edge_label", ""),
            "fact_type": hit.payload.get("fact_type", ""),
            "source_record": hit.payload.get("source_record", ""),
            "score": hit.score,
        }
        for hit in response.points
    ]
