"""Triage agent — polls pending_triage records and resolves their classification.

Structure mirrors Indexer/Curator: threaded polling loop, atomic claim
via UPDATE-RETURNING (`pending_triage` → `triaging`), LLM check, final
classification written via store.set_classification.

Crash recovery: on startup any records stuck in `triaging` (previous run
died mid-process) are reset to `pending_triage` so they retry.
"""

from __future__ import annotations

import threading
import traceback
from typing import Any

from pearscarf import log
from pearscarf.agents.base import BaseAgent
from pearscarf.indexing.extraction_tools import (
    CheckAliasTool,
    FindEntityTool,
    GetEntityContextTool,
    SearchEntitiesTool,
)
from pearscarf.knowledge import (
    load as load_prompt,
    load_onboarding_block,
    load_relevancy_guidance,
)
from pearscarf.storage import store
from pearscarf.storage.db import _get_conn, init_db
from pearscarf.tools import BaseTool, ToolRegistry


TRIAGE_POLL_INTERVAL = 5


class ClassifyTriageTool(BaseTool):
    """The triage agent calls this once at the end to commit its decision."""

    name = "classify"
    description = (
        "Emit your final classification decision with reasoning. Call this "
        "exactly once, after you have gathered whatever graph context you need."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "classification": {
                "type": "string",
                "enum": [store.RELEVANT, store.NOISE, store.UNCERTAIN],
                "description": "Your final decision.",
            },
            "reasoning": {
                "type": "string",
                "description": "Why you chose this classification.",
            },
        },
        "required": ["classification", "reasoning"],
    }

    def __init__(self) -> None:
        self.result: dict | None = None

    def execute(self, **kwargs: Any) -> str:
        self.result = {
            "classification": kwargs["classification"],
            "reasoning": kwargs.get("reasoning", ""),
        }
        return f"classification recorded: {kwargs['classification']}"


class TriageAgent:
    """Background agent that drains the pending_triage queue."""

    def __init__(self, log_fn=None) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._log_fn = log_fn

    def _print(self, msg: str) -> None:
        if self._log_fn:
            self._log_fn(f"[triage] {msg}")

    def _reset_stale_triaging(self) -> None:
        """Reset records stuck in `triaging` back to `pending_triage`.

        Called on startup. A previous run may have claimed records and
        died before writing the final classification — this lets them
        retry.
        """
        with _get_conn() as conn:
            rows = conn.execute(
                "UPDATE records SET classification = %s "
                "WHERE classification = %s RETURNING id",
                (store.PENDING_TRIAGE, store.TRIAGING),
            ).fetchall()
            if rows:
                conn.commit()
                self._print(f"reset {len(rows)} stale triaging record(s)")

    def _claim_one(self) -> dict | None:
        """Atomically claim the oldest pending_triage record."""
        with _get_conn() as conn:
            row = conn.execute(
                "UPDATE records SET classification = %s "
                "WHERE id = ("
                "  SELECT id FROM records "
                "  WHERE classification = %s "
                "  ORDER BY created_at ASC LIMIT 1 "
                "  FOR UPDATE SKIP LOCKED"
                ") RETURNING id, type, source, content, metadata, expert_name",
                (store.TRIAGING, store.PENDING_TRIAGE),
            ).fetchone()
            conn.commit()
            return dict(row) if row else None

    def _release_claim(self, record_id: str) -> None:
        """Return a claimed record to the queue for retry on failure."""
        store.set_classification(record_id, store.PENDING_TRIAGE)

    def _build_prompt(self, record: dict) -> str:
        """Compose the triage system prompt: role + onboarding + expert guidance."""
        expert_name = record.get("expert_name") or ""
        guidance = load_relevancy_guidance(expert_name)
        guidance_block = ""
        if guidance and guidance.strip():
            guidance_block = (
                f"## Relevancy guidance for {expert_name}\n\n"
                f"{guidance.strip()}\n\n---\n\n"
            )
        else:
            log.write(
                "triage", "--", "warning",
                f"no relevancy guidance for expert {expert_name!r} — "
                "falling back to onboarding-only framing",
            )
        return (
            load_prompt("triage_agent")
            + "\n\n"
            + load_onboarding_block()
            + guidance_block
        )

    def _process(self, record: dict) -> None:
        """Run triage on a claimed record."""
        record_id = record["id"]

        registry = ToolRegistry()
        registry.register(FindEntityTool())
        registry.register(SearchEntitiesTool())
        registry.register(CheckAliasTool())
        registry.register(GetEntityContextTool())
        classify_tool = ClassifyTriageTool()
        registry.register(classify_tool)

        system_prompt = self._build_prompt(record)
        user_message = (
            f"Record ({record_id}, {record.get('type', '?')}):\n\n"
            f"{record.get('content') or '(no content)'}"
        )

        agent = BaseAgent(
            tool_registry=registry,
            system_prompt=system_prompt,
            agent_name="triage_agent",
        )
        agent.run(user_message)

        if classify_tool.result is None:
            log.write(
                "triage", "--", "warning",
                f"triage didn't call classify for {record_id} — marking uncertain",
            )
            store.set_classification(record_id, store.UNCERTAIN)
            return

        result = classify_tool.result
        store.set_classification(record_id, result["classification"])
        log.write(
            "triage", "--", "action",
            f"{record_id} -> {result['classification']}: {result['reasoning'][:160]}",
        )
        self._print(f"{record_id} -> {result['classification']}")

    def _loop(self) -> None:
        init_db()
        self._reset_stale_triaging()
        while not self._stop.is_set():
            record = self._claim_one()
            if record is None:
                self._stop.wait(TRIAGE_POLL_INTERVAL)
                continue
            try:
                self._process(record)
            except Exception:
                traceback.print_exc()
                self._release_claim(record["id"])

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, name="triage", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def run_foreground(self) -> None:
        """Run the triage loop in the foreground (blocking)."""
        try:
            self._loop()
        except KeyboardInterrupt:
            pass
