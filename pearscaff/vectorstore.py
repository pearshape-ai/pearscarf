"""Vector storage layer — Qdrant wrapper.

Lazy-initialized. The Qdrant client and sentence-transformers model
only load on first use, so commands that don't need vector search stay fast.
"""

from __future__ import annotations

import uuid

from pearscaff.config import QDRANT_URL

_client = None
_model = None

COLLECTION_NAME = "records"
VECTOR_SIZE = 384  # all-MiniLM-L6-v2 output dimension


def _record_id_to_uuid(record_id: str) -> str:
    """Deterministic UUID from a string record ID (e.g. 'email_001')."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, record_id))


def _get_client():
    """Lazy-init Qdrant client and ensure collection exists."""
    global _client
    if _client is None:
        from qdrant_client import QdrantClient
        _client = QdrantClient(url=QDRANT_URL)
        _ensure_collection()
    return _client


def _get_model():
    """Lazy-init sentence-transformers model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _ensure_collection() -> None:
    """Create the records collection if it doesn't exist."""
    from qdrant_client.models import Distance, VectorParams
    collections = [c.name for c in _client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        _client.create_collection(
            collection_name=COLLECTION_NAME,
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
    payload = {**metadata, "content": content, "record_id": record_id}
    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[PointStruct(
            id=_record_id_to_uuid(record_id),
            vector=vector,
            payload=payload,
        )],
    )


def query(
    query_text: str,
    n_results: int = 5,
    where: dict | None = None,
) -> list[dict]:
    """Query Qdrant for similar records.

    Returns list of dicts with keys: id, content, metadata, distance.
    """
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    client = _get_client()
    vector = _embed(query_text)

    query_filter = None
    if where:
        conditions = []
        for key, value in where.items():
            conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))
        query_filter = Filter(must=conditions)

    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=vector,
        limit=n_results,
        query_filter=query_filter,
    )

    output = []
    for hit in results:
        payload = hit.payload or {}
        record_id = payload.get("record_id", str(hit.id))
        output.append({
            "id": record_id,
            "content": payload.get("content", ""),
            "metadata": {k: v for k, v in payload.items() if k not in ("content", "record_id")},
            "distance": 1.0 - hit.score,  # Qdrant cosine returns similarity; callers expect distance
        })
    return output
