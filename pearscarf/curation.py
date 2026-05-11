"""Curation — Consumer that drains the curator_queue after Extraction writes facts.

Polls `curator_queue` for unclaimed entries, claims one at a time,
processes it (expiry scan + confidence upgrade scan + supersession scan),
and deletes the entry. One entry at a time — no concurrency.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime

from pearscarf import log
from pearscarf.agents.llm_client import get_llm_client
from pearscarf.config import CURATOR_CLAIM_TIMEOUT, CURATOR_POLL_INTERVAL, MODEL, PROVIDER
from pearscarf.consumer import Consumer
from pearscarf.knowledge import load as load_prompt
from pearscarf.storage import graph
from pearscarf.storage.db import _get_conn, init_db
from pearscarf.tracing import trace_child, trace_span
from pearscarf.tracked_call import _record_id_var, _run_id_var, tracked_call


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Curation(Consumer):
    """Consumer that drains the curator_queue."""

    name = "curation"
    default_poll_interval = float(CURATOR_POLL_INTERVAL)

    def __init__(self, poll_interval: float | None = None) -> None:
        super().__init__(poll_interval=poll_interval)
        self._last_cycle_upgrades = 0
        self._last_cycle_expired = 0
        self._last_cycle_superseded = 0
        self._last_cycle_at: str | None = None
        self._current_record_id: str | None = None
        # Cumulative judge LLM usage across the consumer's lifetime.
        self.total_input_tokens = 0
        self.total_output_tokens = 0

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
                        self.name,
                        "--",
                        "warning",
                        f"reset timed-out claim: {r['record_id']} (claimed at {r['claimed_at']})",
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
            self.name,
            "--",
            "action",
            f"expiry notification reserved for {edge['edge_id']}",
        )

    def _scan_expired(self) -> int:
        """Stale all ASSERTED[commitment|promise] edges past their valid_until. Returns count."""
        today = graph.utc_to_local_date(datetime.now(UTC).isoformat())
        expired = graph.get_expired_commitments(today)

        for edge in expired:
            self._notify_expiry(edge)
            graph.mark_fact_stale(edge["edge_id"], replaced_by_id=None)
            log.write(
                self.name,
                "--",
                "action",
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
                    self.name,
                    "--",
                    "action",
                    f"confidence upgraded: {edge['edge_id']} inferred → stated "
                    f"({edge['from_name']} → {edge['to_name']})",
                )
                upgraded += 1

        return upgraded

    def _scan_superseded(self, record_id: str) -> int:
        """Detect superseded edges anchored on each newly-extracted edge.

        For each new edge written by this record (the "trigger"):
        1. Find non-stale siblings sharing the same `from_id` (any
           `edge_label`, any `fact_type`, any target). The LLM judge decides
           whether each sibling describes the same underlying claim. Catches
           Day-different, fact-type-aliased, and cross-edge-label supersession.
           Edges from the same record are excluded — a record's own edges are
           treated as a coherent atomic set, not as supersession candidates of
           each other.
        2. Ask the LLM judge for the pairwise relationship between the trigger
           and each sibling: `trigger_supersedes_sibling`, `sibling_supersedes_trigger`,
           or `coexist`.
        3. Apply the decisions:
           - `trigger_supersedes_sibling` → mark sibling stale, replaced_by=trigger.
           - `sibling_supersedes_trigger` → mark trigger stale, replaced_by=that
             sibling. If multiple siblings supersede the trigger, replaced_by
             points to the freshest (by `source_at`).

        Returns the count of edges staled this scan.
        """
        new_edges = graph.get_edges_by_source_record(record_id)
        staled = 0

        for new_edge in new_edges:
            siblings = graph.get_supersession_siblings(
                new_edge["edge_id"], exclude_record_id=record_id
            )
            if not siblings:
                continue

            decisions = self._judge_supersession(new_edge, siblings)
            log.write(
                self.name,
                "--",
                "action",
                f"supersession judged: trigger={new_edge['edge_id']}, "
                f"siblings={len(siblings)}, decisions={len(decisions)}",
            )

            siblings_by_id = {s["edge_id"]: s for s in siblings}
            trigger_supersedors: list[dict] = []

            for d in decisions:
                claimed_id = d.get("sibling_edge_id")
                sibling = siblings_by_id.get(claimed_id) if claimed_id else None
                if sibling is None:
                    continue
                sibling_id = sibling["edge_id"]
                decision = d.get("decision")
                reason = d.get("reason", "")

                if decision == "trigger_supersedes_sibling":
                    graph.mark_fact_stale(sibling_id, replaced_by_id=new_edge["edge_id"])
                    log.write(
                        self.name,
                        "--",
                        "action",
                        f"supersession staled (sibling): {sibling_id} "
                        f"replaced_by={new_edge['edge_id']}, reason: {reason}",
                    )
                    staled += 1
                elif decision == "sibling_supersedes_trigger":
                    trigger_supersedors.append({"sibling": sibling, "reason": reason})

            if trigger_supersedors:
                trigger_supersedors.sort(
                    key=lambda x: x["sibling"].get("source_at") or "",
                    reverse=True,
                )
                winner = trigger_supersedors[0]
                graph.mark_fact_stale(
                    new_edge["edge_id"],
                    replaced_by_id=winner["sibling"]["edge_id"],
                )
                log.write(
                    self.name,
                    "--",
                    "action",
                    f"supersession staled (trigger): {new_edge['edge_id']} "
                    f"replaced_by={winner['sibling']['edge_id']}, reason: {winner['reason']}",
                )
                staled += 1

        return staled

    def _judge_supersession(self, trigger: dict, siblings: list[dict]) -> list[dict]:
        """Call the LLM judge with the trigger edge + its siblings.

        The judge returns a pairwise decision per sibling:
        `trigger_supersedes_sibling`, `sibling_supersedes_trigger`, or `coexist`.

        Wraps `tracked_call` (writes one `llm_calls` row) inside a
        `trace_span`/`trace_child` pair (LangSmith) and sets a fresh `run_id`
        ContextVar so the call is queryable as a coherent run. Accumulates
        token usage on the Curation instance.

        Returns the list of `{sibling_edge_id, decision, reason}` dicts the
        judge produced. Returns `[]` on parse failure (logged).
        """
        if not siblings:
            return []

        system = load_prompt("curator_judge")
        user_msg = self._format_judge_input(trigger, siblings)

        client = get_llm_client(MODEL, explicit_provider=PROVIDER)

        run_id = str(uuid.uuid4())
        run_token = _run_id_var.set(run_id)
        try:
            with trace_span(
                "curator_judge.run",
                run_type="chain",
                metadata={"agent": "curator_judge", "model": MODEL},
                inputs={
                    "trigger_edge_id": trigger.get("edge_id", ""),
                    "sibling_count": len(siblings),
                },
            ) as parent:
                with trace_child(
                    parent,
                    "curator_judge.llm_call",
                    run_type="llm",
                    metadata={"agent": "curator_judge"},
                    inputs={"model": MODEL, "message_count": 1},
                ) as llm_span:
                    # Per-sibling budget plus base structural overhead. Capped at
                    # 16384 — beyond that the Anthropic SDK requires streaming
                    # (10-min generation-time guard). Cost is on actual usage,
                    # not the cap.
                    max_tokens = min(16384, 1024 + 256 * len(siblings))
                    response = tracked_call(
                        client,
                        "curator_judge",
                        system=system,
                        messages=[{"role": "user", "content": user_msg}],
                        tool_schemas=[],
                        model=MODEL,
                        max_tokens=max_tokens,
                    )
                    self.total_input_tokens += response.usage.input_tokens
                    self.total_output_tokens += response.usage.output_tokens
                    if llm_span:
                        llm_span.end(
                            outputs={
                                "stop_reason": response.stop_reason,
                                "input_tokens": response.usage.input_tokens,
                                "output_tokens": response.usage.output_tokens,
                            }
                        )
                if parent:
                    parent.end(outputs={"text_preview": (response.text or "")[:200]})
        finally:
            _run_id_var.reset(run_token)

        text = (response.text or "").strip()
        # Strip ```json fences if present.
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            log.write(
                self.name,
                "--",
                "warning",
                f"judge returned non-JSON: {text[:200]} (error: {exc})",
            )
            return []

        decisions = parsed.get("decisions", [])
        if not isinstance(decisions, list):
            log.write(self.name, "--", "warning", f"judge decisions not a list: {decisions!r}")
            return []
        return decisions

    def _format_judge_input(self, trigger: dict, siblings: list[dict]) -> str:
        """Format the trigger edge + siblings as the user-side judge input."""

        def _to_label(e: dict) -> str:
            to_labels = e.get("to_labels") or []
            if "Day" in to_labels:
                return f"Day({e.get('to_name') or 'unknown'})"
            return e.get("to_name") or "unknown"

        lines = [
            "TRIGGER edge (just written by this record):",
            f"- edge_id: {trigger['edge_id']}",
            f"- fact: {trigger['fact']!r}",
            f"- source_at: {trigger.get('source_at') or 'unknown'}",
            f"- edge_label: {trigger.get('edge_label') or 'unknown'}",
            f"- fact_type: {trigger.get('fact_type') or 'unknown'}",
            f"- from: {trigger.get('from_name') or 'unknown'}",
            f"- to: {_to_label(trigger)}",
            "",
            f"EXISTING SIBLINGS from the same subject (N={len(siblings)}):",
        ]
        for i, sib in enumerate(siblings, start=1):
            lines.extend(
                [
                    f"{i}. edge_id: {sib['edge_id']}",
                    f"   fact: {sib['fact']!r}",
                    f"   source_at: {sib.get('source_at') or 'unknown'}",
                    f"   fact_type: {sib.get('fact_type') or 'unknown'}",
                    f"   from: {sib.get('from_name') or 'unknown'}",
                    f"   to: {_to_label(sib)}",
                ]
            )
        lines.append("")
        lines.append(
            "For each sibling, return one of "
            "`trigger_supersedes_sibling`, `sibling_supersedes_trigger`, or `coexist` "
            "per the system prompt."
        )
        return "\n".join(lines)

    def _process(self, record_id: str) -> None:
        """Process a single record — expiry + confidence upgrade + supersession."""
        log.write(self.name, "--", "action", f"processing {record_id}")

        self._last_cycle_expired = self._scan_expired()
        self._last_cycle_upgrades = self._scan_confidence_upgrades()
        self._last_cycle_superseded = self._scan_superseded(record_id)
        self._last_cycle_at = _now()
