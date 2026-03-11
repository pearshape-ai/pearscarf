"""Indexer — background agent that processes records into the memory layer.

Polls for unindexed records and passes them to the configured memory backend
(Mem0 or SQLite fallback). The backend handles extraction, entity resolution,
graph population, and embedding.
"""

from __future__ import annotations

import threading
import traceback

from pearscaff import log, store
from pearscaff.db import _get_conn, init_db
from pearscaff.memory import MemoryBackend, get_memory_backend


class Indexer:
    """Background agent that indexes records via the memory backend."""

    def __init__(self, memory: MemoryBackend | None = None) -> None:
        self._memory = memory or get_memory_backend()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _build_content(self, record: dict) -> str:
        """Build the record content string for the memory backend."""
        conn = _get_conn()
        record_type = record["type"]

        if record_type == "email":
            row = conn.execute(
                "SELECT sender, recipient, subject, body, received_at "
                "FROM emails WHERE record_id = ?",
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

    def _process_record(self, record: dict) -> None:
        """Build content and pass to the memory backend."""
        record_id = record["id"]

        log.write("indexer", "--", "action", f"processing {record_id}")

        content = self._build_content(record)

        # Append human context if available (enriches extraction)
        human_context = record.get("human_context")
        if human_context:
            content += f"\n\nAdditional context from human:\n{human_context}"

        metadata = {
            "record_id": record_id,
            "type": record["type"],
            "source": record["source"],
            "created_at": record["created_at"],
        }
        if record["type"] == "email":
            email = store.get_email(record_id)
            if email:
                metadata["sender"] = email.get("sender", "")
                metadata["subject"] = email.get("subject", "")

        try:
            self._memory.add(content, metadata)
        except Exception as exc:
            log.write("indexer", "--", "error", f"memory.add failed for {record_id}: {exc}")
            return

        self._mark_indexed(record_id)
        log.write("indexer", "--", "action", f"indexed {record_id}")

    def _mark_indexed(self, record_id: str) -> None:
        conn = _get_conn()
        conn.execute(
            "UPDATE records SET indexed = 1 WHERE id = ?", (record_id,)
        )
        conn.commit()

    def _loop(self) -> None:
        init_db()
        while not self._stop.is_set():
            try:
                conn = _get_conn()
                rows = conn.execute(
                    "SELECT id, type, source, created_at, raw, human_context "
                    "FROM records "
                    "WHERE indexed = 0 AND classification = 'relevant' "
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
