"""Curator — processes the curator_queue after the indexer writes facts.

Polls the queue for unclaimed entries, claims one at a time, processes it,
and deletes the entry. Handles AFFILIATED/ASSERTED dedup, expiry, and
confidence upgrades.
"""

from __future__ import annotations

import threading
import traceback
from datetime import datetime, timezone

from pearscarf import log
from pearscarf.storage import graph
from pearscarf.config import CURATOR_CLAIM_TIMEOUT, CURATOR_POLL_INTERVAL
from pearscarf.storage.db import _get_conn, init_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Curator:
    """Background worker that drains the curator_queue."""

    def __init__(self, log_fn=None) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._log_fn = log_fn
        self._last_cycle_upgrades = 0
        self._last_cycle_expired = 0
        self._last_cycle_at: str | None = None

    def _print(self, msg: str) -> None:
        """Print to terminal if log_fn is set."""
        if self._log_fn:
            self._log_fn(f"[curator] {msg}")

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

    def _notify_expiry(self, edge: dict) -> None:
        """Reserved hook for expiry notifications. No-op for now."""
        log.write(
            "curator", "--", "action",
            f"expiry notification reserved for {edge['edge_id']}",
        )

    def _scan_expired(self) -> int:
        """Stale all ASSERTED[commitment|promise] edges past their valid_until. Returns count."""
        today = graph.utc_to_local_date(datetime.now(timezone.utc).isoformat())
        expired = graph.get_expired_commitments(today)

        for edge in expired:
            self._notify_expiry(edge)
            graph.mark_fact_stale(edge["edge_id"], replaced_by_id=None)
            log.write(
                "curator", "--", "action",
                f"expired {edge['fact_type']} staled — edge_id={edge['edge_id']}, "
                f"from={edge['from_name']}, valid_until={edge['valid_until']}, "
                f"source_record={edge['source_record']}",
            )

        return len(expired)

    def _scan_confidence_upgrades(self) -> int:
        """Upgrade edges from inferred to stated when a source_record confirms it.

        Returns count of edges upgraded.
        """
        edges = graph.get_inferred_multi_source_edges()
        upgraded = 0

        for edge in edges:
            source_records = edge["source_records"]
            has_stated = False
            for sr in source_records:
                if isinstance(sr, dict) and sr.get("confidence") == "stated":
                    has_stated = True
                    break
                # Legacy flat string — can't determine confidence, skip
                if isinstance(sr, str):
                    continue

            if has_stated:
                graph.set_edge_confidence(edge["edge_id"], "stated")
                log.write(
                    "curator", "--", "action",
                    f"confidence upgraded: {edge['edge_id']} inferred → stated "
                    f"({edge['from_name']} → {edge['to_name']})",
                )
                upgraded += 1

        return upgraded

    def _process(self, record_id: str) -> None:
        """Process a single record — expiry + confidence upgrade."""
        log.write("curator", "--", "action", f"processing {record_id}")

        # Expiry scan
        self._last_cycle_expired = self._scan_expired()
        if self._last_cycle_expired:
            self._print(f"  expired {self._last_cycle_expired} commitment(s)")

        # Confidence upgrade
        self._last_cycle_upgrades = self._scan_confidence_upgrades()
        if self._last_cycle_upgrades:
            self._print(f"  upgraded {self._last_cycle_upgrades} edge(s)")

        self._last_cycle_at = _now()

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

                # Count remaining
                with _get_conn() as conn:
                    row = conn.execute(
                        "SELECT COUNT(*) AS c FROM curator_queue WHERE claimed_at IS NULL"
                    ).fetchone()
                    remaining = dict(row).get("c", 0) if row else 0
                self._print(f"processing {record_id} ({remaining} remaining)")

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
