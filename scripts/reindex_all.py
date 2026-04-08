"""Wipe Neo4j graph, Qdrant vectors, and reset Postgres indexed flags for re-extraction.

The Indexer picks up reset records on its next poll cycle.

Usage:
    python scripts/reindex.py
"""

from dotenv import load_dotenv

load_dotenv()

from pearscarf.storage import vectorstore
from pearscarf.storage.db import _get_conn, close_pool, init_db
from pearscarf.storage.neo4j_client import close as neo4j_close, get_session


def main() -> None:
    init_db()

    # Count what will be affected — Neo4j
    with get_session() as session:
        result = session.run("MATCH (n) RETURN count(n) AS c")
        node_count = result.single()["c"]

        result = session.run("MATCH ()-[r]->() RETURN count(r) AS c")
        rel_count = result.single()["c"]

    # Count what will be affected — Qdrant
    try:
        client = vectorstore._get_client()
        collection_info = client.get_collection(vectorstore.COLLECTION_NAME)
        vector_count = collection_info.points_count
    except Exception:
        vector_count = 0

    # Count what will be affected — Postgres
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT count(*) AS c FROM records "
            "WHERE classification = 'relevant' AND indexed = TRUE"
        ).fetchone()
        record_count = row["c"]

    if node_count == 0 and vector_count == 0 and record_count == 0:
        print("Nothing to do — graph and vectors are empty, no indexed records.")
        close_pool()
        neo4j_close()
        return

    print("This will:")
    print(f"  - Delete {node_count} nodes and {rel_count} relationships from Neo4j")
    print(f"  - Delete {vector_count} vectors from Qdrant")
    print(f"  - Reset {record_count} records to unindexed in Postgres")
    print()

    answer = input("Continue? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        close_pool()
        neo4j_close()
        return

    # Wipe Neo4j
    with get_session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    print(f"Deleted {node_count} nodes and {rel_count} relationships from Neo4j.")

    # Wipe Qdrant — delete and recreate collection
    try:
        from qdrant_client.models import Distance, VectorParams

        client = vectorstore._get_client()
        client.delete_collection(vectorstore.COLLECTION_NAME)
        client.create_collection(
            collection_name=vectorstore.COLLECTION_NAME,
            vectors_config=VectorParams(
                size=vectorstore.VECTOR_SIZE, distance=Distance.COSINE
            ),
        )
        # Reset the cached client so _ensure_collection doesn't skip
        vectorstore._client = None
        print(f"Deleted {vector_count} vectors from Qdrant (collection recreated).")
    except Exception as exc:
        print(f"Warning: Qdrant clear failed: {exc}")

    # Reset indexed flags
    with _get_conn() as conn:
        conn.execute(
            "UPDATE records SET indexed = FALSE WHERE classification = 'relevant'"
        )
        conn.commit()
    print(f"Reset {record_count} records to unindexed.")

    print("\nDone. The Indexer will re-process these records on its next poll cycle.")

    close_pool()
    neo4j_close()


if __name__ == "__main__":
    main()
