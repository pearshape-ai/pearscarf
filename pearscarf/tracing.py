"""LangSmith tracing utilities.

When LANGSMITH_TRACING=true, provides decorators and context managers that
create traced spans. When disabled, everything is a no-op with zero overhead.
LangSmith is only imported when tracing is enabled.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from pearscarf.config import LANGSMITH_ENABLED, LANGSMITH_PROJECT


def traceable(
    name: str,
    run_type: str = "llm",
    metadata: dict[str, Any] | None = None,
):
    """Decorator that traces a function call as a LangSmith run.

    No-op when LANGSMITH_ENABLED is False.
    """
    if not LANGSMITH_ENABLED:

        def noop(fn):
            return fn

        return noop

    from langsmith import traceable as ls_traceable

    # langsmith's `traceable` overload types `run_type` as a Literal, but we
    # accept a free-form str from callers (and LangSmith tolerates it at runtime).
    return ls_traceable(  # type: ignore[call-overload]
        name=name,
        run_type=run_type,
        metadata=metadata or {},
        project_name=LANGSMITH_PROJECT,
    )


@contextmanager
def trace_span(
    name: str,
    run_type: str = "chain",
    metadata: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
):
    """Context manager that creates a traced span.

    No-op when LANGSMITH_ENABLED is False.

    Usage:
        with trace_span("worker.run", metadata={"session_id": sid}) as span:
            result = do_work()
            if span:
                span.end(outputs={"result": result})
    """
    if not LANGSMITH_ENABLED:
        yield None
        return

    from langsmith.run_trees import RunTree

    rt = RunTree(
        name=name,
        run_type=run_type,
        extra={"metadata": metadata or {}},
        inputs=inputs or {},
        project_name=LANGSMITH_PROJECT,
    )
    rt.post()
    try:
        yield rt
    except Exception as exc:
        rt.end(error=str(exc))
        rt.patch()
        raise
    else:
        rt.end()
        rt.patch()


@contextmanager
def trace_child(
    parent,
    name: str,
    run_type: str = "llm",
    metadata: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
):
    """Context manager that creates a child span under a parent RunTree.

    If parent is None (tracing disabled), this is a no-op.

    Usage:
        with trace_span("agent.run") as parent:
            with trace_child(parent, "llm_call", inputs={"prompt": p}) as child:
                response = client.messages.create(...)
                if child:
                    child.end(outputs={"response": str(response)})
    """
    if parent is None or not LANGSMITH_ENABLED:
        yield None
        return

    child_rt = parent.create_child(
        name=name,
        run_type=run_type,
        extra={"metadata": metadata or {}},
        inputs=inputs or {},
    )
    child_rt.post()
    try:
        yield child_rt
    except Exception as exc:
        child_rt.end(error=str(exc))
        child_rt.patch()
        raise
    else:
        child_rt.end()
        child_rt.patch()
