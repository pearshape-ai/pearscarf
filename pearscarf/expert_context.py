"""ExpertContext — the single object pearscarf hands to every agent at startup.

Defines three protocols (StorageProtocol, BusProtocol, LogProtocol) that
bound what an agent can do, plus concrete implementations wrapping
existing pearscarf internals. Experts import only from this module — no
reaching into pearscarf's storage, bus, or log packages directly.

The same context is used by default expert agents (gmailscarf,
linearscarf) AND internal agents (worker, retriever, ingest).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


# --- Protocols ---


class StorageProtocol(Protocol):
    def save_record(
        self,
        record_type: str,
        raw: str,
        content: str = "",
        metadata: dict | None = None,
        dedup_key: str | None = None,
    ) -> str | None:
        """Save a record. Returns record_id on success, None on duplicate.

        raw: true source data (JSON, markdown, whatever came from the API).
        content: LLM-ready formatted string the indexer uses for extraction.
        """
        ...

    def get_record(self, record_id: str) -> dict | None:
        """Look up a record by id. Returns the row as a dict, or None."""
        ...

    def mark_relevant(self, record_id: str) -> None:
        """Mark a record as relevant (sets classification = 'relevant')."""
        ...


class BusProtocol(Protocol):
    def send(self, session_id: str, to_agent: str, content: str) -> None:
        """Send a message within a session. from_agent is implicit."""
        ...

    def create_session(self, summary: str) -> str:
        """Create a new session. initiated_by is implicit. Returns session_id."""
        ...

    def subscribe(self, handler: Callable) -> None:
        """Register a handler for write-back messages addressed to this agent.

        The handler receives a message dict and returns a response dict.
        Dispatch is not yet wired — the handler is stored for when that
        lands.
        """
        ...


class LogProtocol(Protocol):
    def write(self, agent: str, event_type: str, message: str) -> None:
        """Write a log entry."""
        ...


# --- ExpertContext ---


@dataclass
class ExpertContext:
    """The entire surface area agents are given at startup.

    Every agent — expert or internal — receives this once. They use it
    for storage, bus messaging, logging, and reading their own config.
    They do not import pearscarf internals.
    """

    bus: BusProtocol
    storage: StorageProtocol
    log: LogProtocol
    config: dict
    expert_name: str


# --- Concrete implementations ---


class PearscarfStorage:
    """Wraps pearscarf.storage.store to implement StorageProtocol."""

    def __init__(self, expert_name: str, expert_version: str = "") -> None:
        self._expert_name = expert_name
        self._expert_version = expert_version

    def save_record(
        self,
        record_type: str,
        raw: str,
        content: str = "",
        metadata: dict | None = None,
        dedup_key: str | None = None,
    ) -> str | None:
        from pearscarf.storage import store

        return store.save_record(
            record_type=record_type,
            raw=raw,
            content=content,
            metadata=metadata,
            dedup_key=dedup_key,
            source=self._expert_name,
            expert_name=self._expert_name,
            expert_version=self._expert_version,
        )

    def get_record(self, record_id: str) -> dict | None:
        from pearscarf.storage import store

        return store.get_record(record_id)

    def mark_relevant(self, record_id: str) -> None:
        from pearscarf.storage import store

        store.mark_relevant(record_id)


class PearscarfBus:
    """Wraps pearscarf's MessageBus to implement BusProtocol.

    send() and create_session() delegate to the underlying MessageBus,
    filling in from_agent / initiated_by automatically from expert_name.

    subscribe() registers a write-back handler. The handler is stored
    but dispatch is not yet wired end-to-end — a background loop that
    polls for write-back messages and calls handlers is a follow-up.
    """

    def __init__(self, bus: Any, expert_name: str) -> None:
        # bus is a pearscarf.bus.MessageBus instance. Typed as Any to
        # avoid importing it at module level (experts should not depend
        # on pearscarf.bus directly).
        self._bus = bus
        self._expert_name = expert_name
        self._handler: Callable | None = None

    def send(self, session_id: str, to_agent: str, content: str) -> None:
        self._bus.send(
            session_id=session_id,
            from_agent=self._expert_name,
            to_agent=to_agent,
            content=content,
        )

    def create_session(self, summary: str) -> str:
        return self._bus.create_session(self._expert_name, summary)

    def subscribe(self, handler: Callable) -> None:
        self._handler = handler


class PearscarfLog:
    """Wraps pearscarf.log to implement LogProtocol."""

    def write(self, agent: str, event_type: str, message: str) -> None:
        from pearscarf import log

        log.write(agent, "--", event_type, message)


# --- Factory ---


def build_context(
    expert_name: str,
    bus: Any,
    config: dict | None = None,
    expert_version: str = "",
) -> ExpertContext:
    """Build a concrete ExpertContext for a given agent.

    Called by pearscarf at startup for each enabled expert (and for
    internal agents). The bus is the running MessageBus instance. The
    config dict is pre-loaded from env/.<expert_name>.env for experts,
    or from pearscarf.config for internal agents.
    """
    return ExpertContext(
        bus=PearscarfBus(bus, expert_name),
        storage=PearscarfStorage(expert_name, expert_version),
        log=PearscarfLog(),
        config=config or {},
        expert_name=expert_name,
    )
