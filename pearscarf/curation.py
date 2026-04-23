"""Curation — Consumer that drains the curator_queue after Extraction writes facts.

Polls `curator_queue` for unclaimed entries, claims one at a time,
processes it (expiry scan + confidence upgrade scan), and deletes the
entry. One entry at a time — no concurrency.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pearscarf import log
from pearscarf.consumer import Consumer
from pearscarf.config import CURATOR_CLAIM_TIMEOUT, CURATOR_POLL_INTERVAL
from pearscarf.storage import graph
from pearscarf.storage.db import _get_conn, init_db
from pearscarf.tracked_call import _record_id_var


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Curation(Consumer):
    """Consumer that drains the curator_queue."""

    name = "curation"
    default_poll_interval = float(CURATOR_POLL_INTERVAL)

    def __init__(self, poll_interval: float | None = None) -> None:
        super().__init__(poll_interval=poll_interval)
        self._last_cycle_upgrades = 0
        self._last_cycle_expired = 0
        self._last_cycle_at: str | None = None
        self._current_record_id: str | None = None

    # --- Consumer hooks ---

    def _setup(self) -> None:
        init_db()

    def _next(self) -> str | None:
        # Crash recovery: reclaim anything held too long.
        self._reset_timed_out_claims()
        return self._claim_one()

    def _handle(self, record_id: str) -> None:
        self._current_record_id = record_id
        token = _record_id_var.set(record_id)
        try:
            self._process(record_id)
            self._delete_entry(record_id)
        except Exception:
            try:
                self._release_claim(record_id)
            except Exception:
                pass
            raise  # Consumer base logs + continues
        finally:
            self._current_record_id = None
            _record_id_var.reset(token)

    # --- Queue operations ---

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
                        self.name, "--", "warning",
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

    # --- Graph operations ---

    def _notify_expiry(self, edge: dict) -> None:
        """Reserved hook for expiry notifications. No-op for now."""
        log.write(
            self.name, "--", "action",
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
                self.name, "--", "action",
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
                    self.name, "--", "action",
                    f"confidence upgraded: {edge['edge_id']} inferred → stated "
                    f"({edge['from_name']} → {edge['to_name']})",
                )
                upgraded += 1

        return upgraded

    def _process(self, record_id: str) -> None:
        """Process a single record — expiry + confidence upgrade."""
        log.write(self.name, "--", "action", f"processing {record_id}")

        self._last_cycle_expired = self._scan_expired()
        self._last_cycle_upgrades = self._scan_confidence_upgrades()
        self._last_cycle_at = _now()
