"""Observability wrapper around LLM API calls.

Every LLM call writes one row to `llm_calls`, with its system prompt
deduped into `llm_prompts` and a runtime-snapshot row in `runtimes`.
See `notion/design/observability-and-safety.md`.

Today the only wrapper is Anthropic-specific (`tracked_anthropic_call`);
the schema carries `provider` so adding a second provider later is an
additive adapter, no migration.
"""

from __future__ import annotations

import hashlib
import os
import socket
import time
import traceback
import uuid
from contextvars import ContextVar
from typing import Any

from psycopg.types.json import Jsonb

import pearscarf
from pearscarf import log
from pearscarf.storage.db import _get_conn, init_db


# ContextVars set by the Consumer / BaseAgent before / during agent.run().
# Defaults mean: "we're running outside a Consumer context" (e.g. `psc chat`).
_runtime_id_var: ContextVar[str | None] = ContextVar("runtime_id", default=None)
_consumer_var: ContextVar[str | None] = ContextVar("consumer", default=None)
_record_id_var: ContextVar[str | None] = ContextVar("record_id", default=None)
_session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)
_run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)
_turn_index_var: ContextVar[int] = ContextVar("turn_index", default=0)


def register_runtime(consumer_name: str) -> str:
    """Insert one `runtimes` row for this Consumer boot. Return its id.

    Called by `Consumer._loop()` at startup. The returned id is what
    every subsequent `llm_calls` row written from this Consumer's
    thread will carry as `runtime_id`.
    """
    init_db()
    runtime_id = str(uuid.uuid4())
    try:
        expert_versions = _collect_expert_versions()
    except Exception:
        expert_versions = {}
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO runtimes (id, consumer, pearscarf_version, expert_versions, "
                "hostname, pid) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    runtime_id,
                    consumer_name,
                    pearscarf.__version__,
                    Jsonb(expert_versions),
                    socket.gethostname(),
                    os.getpid(),
                ),
            )
            conn.commit()
    except Exception:
        # Observability must never break the main flow.
        log.write(consumer_name, "--", "warning", "register_runtime failed")
        traceback.print_exc()
    return runtime_id


def _collect_expert_versions() -> dict[str, str]:
    """Snapshot installed expert names → versions for the current process."""
    try:
        from pearscarf.registry import get_registry
        registry = get_registry()
        return {e.name: e.version for e in registry.enabled_experts()}
    except Exception:
        return {}


def tracked_anthropic_call(client: Any, agent_name: str, **kwargs: Any) -> Any:
    """Wrap anthropic.messages.create. Log one row to llm_calls.

    Any failure in the logging path is swallowed — observability is
    never allowed to break the main flow.
    """
    system_prompt = kwargs.get("system", "") or ""
    prompt_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
    model = kwargs.get("model", "")

    start = time.monotonic()
    try:
        response = client.messages.create(**kwargs)
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        _safe_log(
            agent_name=agent_name,
            model=model,
            system_prompt=system_prompt,
            prompt_hash=prompt_hash,
            response=None,
            latency_ms=latency_ms,
            error=str(exc),
        )
        raise

    latency_ms = int((time.monotonic() - start) * 1000)
    _safe_log(
        agent_name=agent_name,
        model=model,
        system_prompt=system_prompt,
        prompt_hash=prompt_hash,
        response=response,
        latency_ms=latency_ms,
        error=None,
    )
    return response


def _safe_log(**kwargs: Any) -> None:
    try:
        _log_call(**kwargs)
    except Exception:
        log.write("tracked_call", "--", "warning", "llm_calls log write failed")
        traceback.print_exc()


def _log_call(
    agent_name: str,
    model: str,
    system_prompt: str,
    prompt_hash: str,
    response: Any,
    latency_ms: int,
    error: str | None,
) -> None:
    consumer = _consumer_var.get() or "chat"
    runtime_id = _runtime_id_var.get()
    run_id = _run_id_var.get() or str(uuid.uuid4())
    turn_index = _turn_index_var.get()
    record_id = _record_id_var.get()
    session_id = _session_id_var.get()

    # Chat / one-off paths may not have a runtime row; lazily create one.
    if runtime_id is None:
        runtime_id = register_runtime(consumer)

    if response is not None:
        usage = response.usage
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        cache_creation = getattr(usage, "cache_creation_input_tokens", None) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", None) or 0
        stop_reason = response.stop_reason or "unknown"
        tool_names = [
            block.name for block in response.content if getattr(block, "type", "") == "tool_use"
        ]
        tool_calls = tool_names if tool_names else None
    else:
        input_tokens = 0
        output_tokens = 0
        cache_creation = 0
        cache_read = 0
        stop_reason = "error"
        tool_calls = None

    with _get_conn() as conn:
        # Dedup-upsert the prompt body.
        conn.execute(
            "INSERT INTO llm_prompts (hash, body) VALUES (%s, %s) "
            "ON CONFLICT (hash) DO NOTHING",
            (prompt_hash, system_prompt),
        )
        conn.execute(
            "INSERT INTO llm_calls ("
            "runtime_id, consumer, agent_name, pearscarf_version, "
            "run_id, turn_index, provider, model, prompt_hash, stop_reason, tool_calls, "
            "input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, "
            "latency_ms, record_id, session_id, error"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                runtime_id,
                consumer,
                agent_name,
                pearscarf.__version__,
                run_id,
                turn_index,
                "anthropic",
                model,
                prompt_hash,
                stop_reason,
                Jsonb(tool_calls) if tool_calls is not None else None,
                input_tokens,
                output_tokens,
                cache_creation,
                cache_read,
                latency_ms,
                record_id,
                session_id,
                error,
            ),
        )
        conn.commit()
