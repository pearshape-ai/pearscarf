"""Curator — processes the curator_queue after the indexer writes facts.

Polls the queue for unclaimed entries, claims one at a time, processes it,
and deletes the entry. Processing logic is a stub until 1.14.2+.
"""

from __future__ import annotations

import threading
import traceback

from pearscarf import log
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
        """Process a single record. Stub — filled in by 1.14.2+."""
        log.write("curator", "--", "action", f"processing {record_id}")
        # TODO: graph curation logic goes here

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
