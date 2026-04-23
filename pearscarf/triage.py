"""Triage — Consumer that classifies pending records as relevant / noise / uncertain.

Polls `records WHERE classification='pending_triage'`, atomically claims
one via `UPDATE-RETURNING` (`pending_triage` → `triaging`), runs
`TriageAgent` with read-only graph tools, and writes the final
classification through `store.set_classification`.

Crash recovery: on `_setup` any records stuck in `triaging` (previous run
died mid-process) are reset to `pending_triage` so they retry.
"""

from __future__ import annotations

from typing import Any

from pearscarf import log
from pearscarf.agents.base import BaseAgent
from pearscarf.consumer import Consumer
from pearscarf.graph_access_tools import (
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
from pearscarf.tracked_call import _record_id_var


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


class TriageAgent(BaseAgent):
    """LLM agent spawned per record by `Triage` to classify relevance.

    Thin named subclass of `BaseAgent` — same run loop, fixed agent_name.
    """

    def __init__(
        self,
        tool_registry,
        system_prompt: str = "",
        on_tool_call=None,
        on_text=None,
        on_tool_result=None,
    ) -> None:
        super().__init__(
            tool_registry=tool_registry,
            system_prompt=system_prompt,
            agent_name="triage_agent",
            on_tool_call=on_tool_call,
            on_text=on_text,
            on_tool_result=on_tool_result,
        )


class Triage(Consumer):
    """Consumer that drains the pending_triage queue."""

    name = "triage"
    default_poll_interval = 5.0

    def __init__(self, poll_interval: float | None = None) -> None:
        super().__init__(poll_interval=poll_interval)

    # --- Consumer hooks ---

    def _setup(self) -> None:
        init_db()
        self._reset_stale_triaging()

    def _next(self) -> dict | None:
        return self._claim_one()

    def _handle(self, record: dict) -> None:
        token = _record_id_var.set(record["id"])
        try:
            self._process(record)
        except Exception:
            # Release the claim so the record retries on the next loop.
            self._release_claim(record["id"])
            raise  # Consumer base logs + continues.
        finally:
            _record_id_var.reset(token)

    # --- Triage-specific logic ---

    def _reset_stale_triaging(self) -> None:
        """Reset records stuck in `triaging` back to `pending_triage`.

        A previous run may have claimed records and died before writing
        the final classification — this lets them retry.
        """
        with _get_conn() as conn:
            rows = conn.execute(
                "UPDATE records SET classification = %s "
                "WHERE classification = %s RETURNING id",
                (store.PENDING_TRIAGE, store.TRIAGING),
            ).fetchall()
            if rows:
                conn.commit()
                log.write(
                    self.name, "--", "action",
                    f"reset {len(rows)} stale triaging record(s)",
                )

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
                self.name, "--", "warning",
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

        agent = TriageAgent(
            tool_registry=registry,
            system_prompt=system_prompt,
        )
        agent.run(user_message)

        if classify_tool.result is None:
            log.write(
                self.name, "--", "warning",
                f"triage didn't call classify for {record_id} — marking uncertain",
            )
            store.set_classification(record_id, store.UNCERTAIN)
            return

        result = classify_tool.result
        store.set_classification(record_id, result["classification"])
        log.write(
            self.name, "--", "action",
            f"{record_id} -> {result['classification']}: {result['reasoning'][:160]}",
        )
