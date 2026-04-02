"""Curator — processes the curator_queue after the indexer writes facts.

Polls the queue for unclaimed entries, claims one at a time, processes it,
and deletes the entry. Currently handles AFFILIATED semantic dedup.
"""

from __future__ import annotations

import threading
import traceback

from pearscarf import curator_judge, graph, log
from pearscarf.config import CURATOR_CLAIM_TIMEOUT, CURATOR_POLL_INTERVAL
from pearscarf.db import _get_conn, init_db


class Curator:
    """Background worker that drains the curator_queue."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _reset_timed_out_claims(self) -> None:
        """Release claims that have been held too long (crash recovery)."""
        with _get_conn() as conn:
            rows = conn.execute(
                "UPDATE curator_queue "
                "SET claimed_at = NULL "
                "WHERE claimed_at IS NOT NULL "
                "AND claimed_at < now() - interval '%s seconds' "
                "RETURNING record_id, claimed_at",
                (CURATOR_CLAIM_TIMEOUT,),
            ).fetchall()
            if rows:
                conn.commit()
                for r in rows:
                    log.write(
                        "curator", "--", "warning",
                        f"reset timed-out claim: {r['record_id']} "
                        f"(claimed at {r['claimed_at']})",
                    )

    def _claim_one(self) -> str | None:
        """Claim the oldest unclaimed entry. Returns record_id or None."""
        with _get_conn() as conn:
            row = conn.execute(
                "UPDATE curator_queue "
                "SET claimed_at = now() "
                "WHERE record_id = ("
                "  SELECT record_id FROM curator_queue "
                "  WHERE claimed_at IS NULL "
                "  ORDER BY queued_at ASC "
                "  LIMIT 1 "
                "  FOR UPDATE SKIP LOCKED"
                ") "
                "RETURNING record_id",
            ).fetchone()
            conn.commit()
            return row["record_id"] if row else None

    def _delete_entry(self, record_id: str) -> None:
        """Remove a processed entry from the queue."""
        with _get_conn() as conn:
            conn.execute(
                "DELETE FROM curator_queue WHERE record_id = %s",
                (record_id,),
            )
            conn.commit()

    def _release_claim(self, record_id: str) -> None:
        """Release a claim back to unclaimed (for retry)."""
        with _get_conn() as conn:
            conn.execute(
                "UPDATE curator_queue SET claimed_at = NULL WHERE record_id = %s",
                (record_id,),
            )
            conn.commit()

    def _process(self, record_id: str) -> None:
        """Process a single record — AFFILIATED semantic dedup."""
        log.write("curator", "--", "action", f"processing {record_id}")

        # Step 1: Get this record's edges (including dedup-merged)
        edges = graph.get_edges_by_source_record(record_id)
        affiliated = [e for e in edges if e["edge_label"] == "AFFILIATED" and not e["stale"]]

        if not affiliated:
            return

        # Step 2: Group by slot (from_id, fact_type, to_id)
        slots: dict[tuple, list[dict]] = {}
        for e in affiliated:
            key = (e["from_id"], e["fact_type"], e["to_id"])
            slots.setdefault(key, []).append(e)

        # Step 3: For each slot, get all current edges and run dedup
        for (from_id, fact_type, to_id), slot_edges in slots.items():
            all_edges = graph.get_edges_for_slot(from_id, "AFFILIATED", fact_type, to_id)

            if len(all_edges) <= 1:
                continue

            from_name = slot_edges[0]["from_name"]
            to_name = slot_edges[0]["to_name"]

            # Step 4: Call judge
            groups = curator_judge.judge_equivalence(all_edges, "AFFILIATED")

            log.write(
                "curator", "--", "action",
                f"affiliated dedup: slot ({from_name}, {fact_type}, {to_name}) — "
                f"{len(all_edges)} candidates, {len(groups)} groups",
            )

            # Step 5: Process groups
            for group_ids in groups:
                if len(group_ids) <= 1:
                    continue

                # Find the edges in this group
                group_edges = [e for e in all_edges if e["edge_id"] in group_ids]
                if not group_edges:
                    continue

                # Sort by source_at descending — most recent is survivor
                group_edges.sort(key=lambda e: e["source_at"], reverse=True)
                survivor = group_edges[0]

                for older in group_edges[1:]:
                    if older["source_at"] == survivor["source_at"]:
                        log.write(
                            "curator", "--", "action",
                            f"affiliated unresolved: equal source_at for "
                            f"{older['edge_id']} and {survivor['edge_id']} — skipped",
                        )
                        continue
                    graph.mark_fact_stale(older["edge_id"], survivor["edge_id"])
                    log.write(
                        "curator", "--", "action",
                        f"affiliated staled: {older['edge_id']} → {survivor['edge_id']} "
                        f"(source_at: {older['source_at']} < {survivor['source_at']})",
                    )

    def _loop(self) -> None:
        init_db()
        record_id = None
        while not self._stop.is_set():
            try:
                # Step 1: Reset timed-out claims
                self._reset_timed_out_claims()

                # Step 2: Claim one entry
                record_id = self._claim_one()
                if record_id is None:
                    self._stop.wait(CURATOR_POLL_INTERVAL)
                    continue

                # Step 3: Process
                try:
                    self._process(record_id)
                except Exception as exc:
                    log.write(
                        "curator", "--", "warning",
                        f"processing failed for {record_id}: {exc}",
                    )
                    # Handled exception — delete entry, don't retry logic errors

                # Step 4: Delete entry
                self._delete_entry(record_id)
                record_id = None

            except Exception:
                # Unhandled exception in claim/delete path
                traceback.print_exc()
                if record_id:
                    try:
                        self._release_claim(record_id)
                    except Exception:
                        pass
                    record_id = None

            self._stop.wait(CURATOR_POLL_INTERVAL)

    def start(self) -> None:
        """Start the curator in a background daemon thread."""
        self._thread = threading.Thread(
            target=self._loop, name="curator", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def run_foreground(self) -> None:
        """Run the curator loop in the foreground (blocking)."""
        try:
            self._loop()
        except KeyboardInterrupt:
            pass
