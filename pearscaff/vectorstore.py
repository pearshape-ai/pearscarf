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


def query(
    query_text: str,
    n_results: int = 5,
    where: dict | None = None,
) -> list[dict]:
    """Query Qdrant for similar records."""
    client = _get_client()
    vector = _embed(query_text)

    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=vector,
        limit=n_results,
    )

    return [
        {
            "id": hit.payload.get("record_id", ""),
            "content": hit.payload.get("content", ""),
            "metadata": {
                k: v for k, v in hit.payload.items()
                if k not in ("record_id", "content")
            },
            "score": hit.score,
        }
        for hit in results
    ]
