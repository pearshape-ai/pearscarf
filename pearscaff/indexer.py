"""Indexer — background agent that processes records into the knowledge graph.

Polls for unindexed records and runs LLM extraction → entity resolution →
graph population → Qdrant embedding.
"""

from __future__ import annotations

import threading
import traceback

from pearscaff import log
from pearscaff.db import _get_conn, init_db

# Extraction system prompt: pearscaff/prompts/extraction.md


class Indexer:
    """Background agent that indexes records via LLM extraction."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _build_content(self, record: dict) -> str:
        """Build the record content string for extraction."""
        record_type = record["type"]

        if record_type == "email":
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT sender, recipient, subject, body, received_at "
                    "FROM emails WHERE record_id = %s",
                    (record["id"],),
                ).fetchone()
            if row:
                email = dict(row)
                parts = []
                if email["sender"]:
                    parts.append(f"From: {email['sender']}")
                if email["recipient"]:
                    parts.append(f"To: {email['recipient']}")
                if email["subject"]:
                    parts.append(f"Subject: {email['subject']}")
                if email["received_at"]:
                    parts.append(f"Date: {email['received_at']}")
                if email["body"]:
                    body = email["body"][:3000]
                    parts.append(f"\n{body}")
                return "\n".join(parts)

        # Fallback: use raw content from records table
        return record.get("raw") or "(no content)"

    def _extract(self, record_type: str, record_id: str, content: str) -> dict:
        """LLM extraction of entities, relationships, and facts. (stubbed)"""
        return {}

    def _resolve_entity(self, extracted: dict) -> str:
        """Resolve an extracted entity against the graph. (stubbed)"""
        return ""

    def _process_record(self, record: dict) -> None:
        """Process a single record. (stubbed — no extraction or embedding)"""
        record_id = record["id"]

        log.write("indexer", "--", "action", f"processing {record_id}")

        content = self._build_content(record)  # noqa: F841 — kept for future extraction

        self._mark_indexed(record_id)
        log.write("indexer", "--", "action", f"indexed {record_id} (no extraction)")

    def _mark_indexed(self, record_id: str) -> None:
        with _get_conn() as conn:
            conn.execute(
                "UPDATE records SET indexed = TRUE WHERE id = %s", (record_id,)
            )
            conn.commit()

    def _loop(self) -> None:
        init_db()
        while not self._stop.is_set():
            try:
                with _get_conn() as conn:
                    rows = conn.execute(
                        "SELECT id, type, source, created_at, raw, human_context "
                        "FROM records "
                        "WHERE indexed = FALSE AND classification = 'relevant' "
                        "ORDER BY created_at"
                    ).fetchall()

                if rows:
                    log.write(
                        "indexer", "--", "action",
                        f"found {len(rows)} unindexed record(s): "
                        + ", ".join(r["id"] for r in rows),
                    )
                    for row in rows:
                        if self._stop.is_set():
                            break
                        self._process_record(dict(row))
            except Exception:
                traceback.print_exc()

            self._stop.wait(5)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, name="indexer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
