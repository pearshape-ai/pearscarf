"""Wipe all system state: Postgres records, Neo4j graph, Qdrant vectors.

Unlike reindex_all.py which preserves records and resets indexed flags,
this script deletes everything for a fully clean slate.

Usage:
    python scripts/erase_all.py
"""

from dotenv import load_dotenv

load_dotenv()

from pearscarf.storage import vectorstore
from pearscarf.storage.db import _get_conn, close_pool, init_db
from pearscarf.storage.neo4j_client import close as neo4j_close, get_session


def main() -> None:
    init_db()

    # --- Count what will be affected ---

    # Neo4j
    with get_session() as session:
        result = session.run("MATCH (n) RETURN count(n) AS c")
        node_count = result.single()["c"]

        result = session.run("MATCH ()-[r]->() RETURN count(r) AS c")
        rel_count = result.single()["c"]

    # Qdrant
    try:
        client = vectorstore._get_client()
        collection_info = client.get_collection(vectorstore.COLLECTION_NAME)
        vector_count = collection_info.points_count
    except Exception:
        vector_count = 0

    # Postgres
    with _get_conn() as conn:
        records_count = conn.execute("SELECT count(*) AS c FROM records").fetchone()["c"]
        emails_count = conn.execute("SELECT count(*) AS c FROM emails").fetchone()["c"]
        issues_count = conn.execute("SELECT count(*) AS c FROM issues").fetchone()["c"]
        changes_count = conn.execute("SELECT count(*) AS c FROM issue_changes").fetchone()["c"]

    total = node_count + vector_count + records_count
    if total == 0:
        print("Nothing to do — all stores are empty.")
        close_pool()
        neo4j_close()
        return

    print("This will DELETE:")
    print(f"  Postgres:  {records_count} records, {emails_count} emails, {issues_count} issues, {changes_count} issue_changes")
    print(f"  Neo4j:     {node_count} nodes, {rel_count} relationships")
    print(f"  Qdrant:    {vector_count} vectors")
    print()

    answer = input("Continue? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        close_pool()
        neo4j_close()
        return

    # --- Wipe Neo4j ---
    with get_session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    print(f"Deleted {node_count} nodes and {rel_count} relationships from Neo4j.")

    # --- Wipe Qdrant ---
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
        vectorstore._client = None
        print(f"Deleted {vector_count} vectors from Qdrant (collection recreated).")
    except Exception as exc:
        print(f"Warning: Qdrant clear failed: {exc}")

    # --- Wipe Postgres records tables (dependency order) ---
    with _get_conn() as conn:
        conn.execute("TRUNCATE curator_queue, issue_changes, issues, emails, records CASCADE")
        conn.commit()
    print(f"Deleted {records_count} records, {emails_count} emails, {issues_count} issues, {changes_count} issue_changes from Postgres.")

    print("\nDone. All system state erased.")

    close_pool()
    neo4j_close()


if __name__ == "__main__":
    main()
