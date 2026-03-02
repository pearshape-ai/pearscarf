"""Vector storage layer — ChromaDB wrapper.

Lazy-initialized. The ChromaDB client and sentence-transformers model
only load on first use, so commands that don't need vector search stay fast.
"""

from __future__ import annotations

import chromadb
from chromadb.utils import embedding_functions

from pearscaff.config import CHROMA_PATH

_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None


def _get_collection() -> chromadb.Collection:
    """Lazy-init ChromaDB client and collection."""
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        _collection = _client.get_or_create_collection(
            name="records",
            embedding_function=ef,
        )
    return _collection


def add_record(record_id: str, content: str, metadata: dict) -> None:
    """Add or update a record's embedding in ChromaDB."""
    collection = _get_collection()
    collection.upsert(
        ids=[record_id],
        documents=[content],
        metadatas=[metadata],
    )


def query(
    query_text: str,
    n_results: int = 5,
    where: dict | None = None,
) -> list[dict]:
    """Query ChromaDB for similar records.

    Returns list of dicts with keys: id, content, metadata, distance.
    """
    collection = _get_collection()
    kwargs: dict = {
        "query_texts": [query_text],
        "n_results": n_results,
    }
    if where:
        kwargs["where"] = where

    results = collection.query(**kwargs)

    output = []
    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for i, rid in enumerate(ids):
        output.append({
            "id": rid,
            "content": documents[i] if i < len(documents) else "",
            "metadata": metadatas[i] if i < len(metadatas) else {},
            "distance": distances[i] if i < len(distances) else 0.0,
        })

    return output
