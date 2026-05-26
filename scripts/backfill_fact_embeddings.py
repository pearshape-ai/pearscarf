"""Backfill fact embeddings into the Qdrant `facts` collection.

One-time migration. Reads every non-stale fact edge from Neo4j and embeds its
`fact` text with the local sentence-transformers model (no API, no tokens), then
upserts into the `facts` collection. Idempotent — point ids derive from the edge
elementId, so re-runs upsert in place.

New facts are embedded automatically at extraction time (see
`Extraction._write_fact_edge`); this backfills facts that predate that change.

Run on the deployment host, where Neo4j + Qdrant + the model are all local:
    python scripts/backfill_fact_embeddings.py --dry-run   # count only, no writes
    python scripts/backfill_fact_embeddings.py             # confirm, then backfill
    python scripts/backfill_fact_embeddings.py --yes       # non-interactive
"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv

load_dotenv()

from pearscarf.storage import vectorstore
from pearscarf.storage.neo4j_client import close as neo4j_close
from pearscarf.storage.neo4j_client import get_session

_FETCH = (
    "MATCH (a)-[r]->(b) "
    "WHERE r.fact IS NOT NULL AND (r.stale IS NULL OR r.stale = false) "
    "RETURN elementId(r) AS edge_id, r.fact AS fact, type(r) AS edge_label, "
    "r.fact_type AS fact_type, r.source_record AS source_record"
)


def _fetch_facts() -> list[dict]:
    """All non-stale fact edges, shaped for `vectorstore.add_fact`."""
    with get_session() as session:
        return [dict(row) for row in session.run(_FETCH).data()]


def backfill(facts: list[dict]) -> int:
    """Embed each fact into the facts collection. Returns the count embedded."""
    embedded = 0
    for f in facts:
        edge_id = f.get("edge_id")
        text = f.get("fact")
        if not edge_id or not text:
            continue
        vectorstore.add_fact(
            edge_id,
            text,
            {
                "edge_label": f.get("edge_label"),
                "fact_type": f.get("fact_type"),
                "source_record": f.get("source_record"),
            },
        )
        embedded += 1
    return embedded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Count facts, write nothing.")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args()

    facts = _fetch_facts()
    collection = vectorstore.FACTS_COLLECTION
    print(f"Found {len(facts)} non-stale fact edge(s) to embed into '{collection}'.")

    if args.dry_run:
        print("Dry run — no writes.")
        neo4j_close()
        return

    if not facts:
        print("Nothing to do.")
        neo4j_close()
        return

    if not args.yes:
        answer = (
            input(f"Embed {len(facts)} fact(s) into Qdrant '{collection}'? [y/N] ").strip().lower()
        )
        if answer != "y":
            print("Aborted.")
            neo4j_close()
            return

    embedded = backfill(facts)
    print(f"Done. Embedded {embedded} fact(s) into '{collection}'.")
    neo4j_close()


if __name__ == "__main__":
    main()
