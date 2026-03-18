"""Wipe Neo4j graph and reset Postgres indexed flags for re-extraction.

The Indexer picks up reset records on its next poll cycle.

Usage:
    python scripts/reindex.py
"""

from dotenv import load_dotenv

load_dotenv()

from pearscaff.db import _get_conn, init_db
from pearscaff.neo4j_client import close as neo4j_close, get_session


def main() -> None:
    init_db()

    # Count what will be affected
    with get_session() as session:
        result = session.run("MATCH (n) RETURN count(n) AS c")
        node_count = result.single()["c"]

        result = session.run("MATCH ()-[r]->() RETURN count(r) AS c")
        rel_count = result.single()["c"]

    with _get_conn() as conn:
        row = conn.execute(
            "SELECT count(*) AS c FROM records "
            "WHERE classification = 'relevant' AND indexed = TRUE"
        ).fetchone()
        record_count = row["c"]

    if node_count == 0 and record_count == 0:
        print("Nothing to do — graph is empty and no indexed records.")
        return

    print(f"This will:")
    print(f"  - Delete {node_count} nodes and {rel_count} relationships from Neo4j")
    print(f"  - Reset {record_count} records to unindexed in Postgres")
    print()

    answer = input("Continue? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        return

    # Wipe Neo4j
    with get_session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    print(f"Deleted {node_count} nodes and {rel_count} relationships from Neo4j.")

    # Reset indexed flags
    with _get_conn() as conn:
        conn.execute(
            "UPDATE records SET indexed = FALSE WHERE classification = 'relevant'"
        )
        conn.commit()
    print(f"Reset {record_count} records to unindexed.")

    print("\nDone. The Indexer will re-process these records on its next poll cycle.")

    neo4j_close()


if __name__ == "__main__":
    main()
