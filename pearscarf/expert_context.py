"""ExpertContext — the single object pearscarf hands to every agent at startup.

Defines three protocols (StorageProtocol, BusProtocol, LogProtocol) that
bound what an agent can do, plus concrete implementations wrapping
existing pearscarf internals. Experts import only from this module — no
reaching into pearscarf's storage, bus, or log packages directly.

The same context is used by default expert agents (gmailscarf,
linearscarf) AND internal agents (assistant, retriever, ingest).
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
        classification: str | None = None,
    ) -> str | None:
        """Save a record. Returns record_id on success, None on duplicate.

        raw: true source data (JSON, markdown, whatever came from the API).
        content: LLM-ready formatted string the indexer uses for extraction.
        classification: when passed, framework stores this label verbatim
            (for experts that classify their own records — e.g. a gmail
            expert running an internal hard filter). When omitted, the
            framework applies the expert's manifest policy: `skip` → the
            record is auto-marked relevant; `required` → the record lands
            as pending_triage for the triage agent to handle.
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

    def __init__(
        self,
        expert_name: str,
        expert_version: str = "",
        relevancy_policy: str = "",
    ) -> None:
        self._expert_name = expert_name
        self._expert_version = expert_version
        self._relevancy_policy = relevancy_policy

    def save_record(
        self,
        record_type: str,
        raw: str,
        content: str = "",
        metadata: dict | None = None,
        dedup_key: str | None = None,
        classification: str | None = None,
    ) -> str | None:
        from pearscarf.storage import store

        record_id = store.save_record(
            record_type=record_type,
            raw=raw,
            content=content,
            metadata=metadata,
            dedup_key=dedup_key,
            source=self._expert_name,
            expert_name=self._expert_name,
            expert_version=self._expert_version,
        )
        if record_id is None:
            return None

        if classification is not None:
            store.set_classification(record_id, classification)
        elif self._relevancy_policy == "skip":
            store.set_classification(record_id, store.RELEVANT)
        elif self._relevancy_policy == "required":
            store.set_classification(record_id, store.PENDING_TRIAGE)

        return record_id

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


def _load_expert_env(expert_name: str) -> dict[str, str]:
    """Load env/.<expert_name>.env and inject into os.environ.

    Returns the parsed key-value pairs as a dict. Values are also set
    in os.environ so that code reading os.getenv() picks them up.
    """
    import os
    from pathlib import Path

    from pearscarf.config import EXPERTS_DIR

    env_dir = Path(EXPERTS_DIR).parent / "env"
    env_path = env_dir / f".{expert_name}.env"
    if not env_path.is_file():
        return {}

    config: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and value:
            config[key] = value
            os.environ.setdefault(key, value)
    return config


def build_context(
    expert_name: str,
    bus: Any,
    config: dict | None = None,
    expert_version: str = "",
) -> ExpertContext:
    """Build a concrete ExpertContext for a given agent.

    Called by pearscarf at startup for each enabled expert (and for
    internal agents). The bus is the running MessageBus instance.
    For experts, the config is auto-loaded from env/.<expert_name>.env.
    Relevancy policy is resolved once from the registry and handed to
    the storage wrapper so it has no runtime dependency on orchestration.
    """
    from pearscarf.registry import get_registry

    if config is None:
        config = _load_expert_env(expert_name)

    expert = get_registry().get_by_name(expert_name)
    relevancy_policy = expert.relevancy_check if expert else ""

    return ExpertContext(
        bus=PearscarfBus(bus, expert_name),
        storage=PearscarfStorage(expert_name, expert_version, relevancy_policy),
        log=PearscarfLog(),
        config=config,
        expert_name=expert_name,
    )


def load_expert(expert_def: Any, bus: Any) -> ExpertContext:
    """Build an ExpertContext and register the expert's connect in the registry.

    Bundles the wiring that every standalone caller of a single expert needs:
    context construction, tools-module import, connect instantiation, and
    per-record-type connect registration. Returns the ExpertContext so the
    caller can pass it to `expert_def.start(ctx)` or similar.

    Callers today: `psc expert <name> start-ingestion` (cli). The equivalent
    inline block in `start_system()` and `psc expert ingest` pre-dates this
    helper and can migrate to it in a later cleanup.
    """
    import importlib

    from pearscarf.registry import get_registry

    ctx = build_context(expert_def.name, bus, expert_version=expert_def.version)
    if expert_def.tools_module:
        tools_mod = importlib.import_module(expert_def.tools_module)
        connect = tools_mod.get_tools(ctx)
        registry = get_registry()
        for rt in expert_def.record_types:
            registry.register_connect(rt, connect)
    return ctx
