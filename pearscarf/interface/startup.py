"""Shared startup sequence for psc run and psc discord.

start_system() does everything both frontends need: credential check,
expert loading, agent wiring, indexer, MCP. Returns a SystemComponents
dataclass the caller uses for shutdown. The caller provides the frontend
(REPL or Discord bot).
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SystemComponents:
    """Running components returned by start_system(). Caller shuts them down."""
    bus: Any
    runners: list = field(default_factory=list)
    indexer: Any = None
    curator: Any = None
    mcp_server: Any = None


def start_system(poll: bool = False, log_fn=None) -> SystemComponents:
    """Boot the full PearScarf system. Returns running components.

    poll: start expert ingester threads (background polling)
    log_fn: callable(str) for status messages (defaults to sys.stdout)
    """
    from pearscarf.agents.runner import AgentRunner
    from pearscarf.agents.worker import create_worker_agent
    from pearscarf.bus import MessageBus
    from pearscarf.config import MCP_PORT
    from pearscarf.expert_context import build_context
    from pearscarf.experts.retriever import create_retriever_for_runner
    from pearscarf.indexing.indexer import Indexer
    from pearscarf.indexing.registry import get_registry
    from pearscarf.interface.install import enforce_credentials_or_exit
    from pearscarf.mcp.mcp_server import MCPServer

    if log_fn is None:
        def log_fn(msg: str) -> None:
            sys.stdout.write(msg + "\r\n")
            sys.stdout.flush()

    # Pre-startup credential check
    enforce_credentials_or_exit()

    bus = MessageBus()
    registry = get_registry()
    components = SystemComponents(bus=bus)

    # --- Boot each expert: tools, LLM agent, ingester ---
    for expert in registry.enabled_experts():
        expert_ctx = build_context(expert.name, bus, expert_version=expert.version)

        # Load and cache connect instance
        if expert.tools_module:
            try:
                tools_mod = importlib.import_module(expert.tools_module)
                connect = tools_mod.get_tools(expert_ctx)
                for rt in expert.record_types:
                    registry.register_connect(rt, connect)
                log_fn(f"{expert.name} tools loaded.")
            except Exception as exc:
                log_fn(f"{expert.name} tools failed: {exc}")

        # Start LLM agent if tools + agent.md exist
        connect = registry.get_connect(expert.record_types[0]) if expert.record_types else None
        if connect is not None:
            prompt_path = expert.knowledge_dir / "agent.md"
            if prompt_path.is_file():
                prompt = prompt_path.read_text()
                tools = connect.get_tools()

                def _make_factory(ctx, p, t):
                    def factory(session_id: str):
                        from pearscarf.agents.expert import ExpertAgent
                        from pearscarf.tools import ToolRegistry
                        reg = ToolRegistry()
                        for tool in t:
                            reg.register(tool)
                        return ExpertAgent(ctx=ctx, domain_prompt=p, tool_registry=reg)
                    return factory

                runner = AgentRunner(expert.name, _make_factory(expert_ctx, prompt, tools), bus)
                runner.start()
                components.runners.append(runner)
                log_fn(f"{expert.name} agent started.")

        # Start ingester
        if poll and expert.ingester_module:
            try:
                thread = expert.start(expert_ctx)
            except Exception as exc:
                log_fn(f"{expert.name} ingester failed to start: {exc}")
                continue
            if thread is None:
                log_fn(f"{expert.name} skipped (no ingester or credentials missing).")
            else:
                log_fn(f"{expert.name} ingester started.")

    # --- Start internal agents ---
    retriever_ctx = build_context("retriever", bus)
    retriever_factory = create_retriever_for_runner(ctx=retriever_ctx)
    retriever_runner = AgentRunner("retriever", retriever_factory, bus)
    retriever_runner.start()
    components.runners.append(retriever_runner)
    log_fn("Retriever started.")

    worker_ctx = build_context("worker", bus)

    def worker_factory(session_id: str):
        return create_worker_agent(ctx=worker_ctx, session_id=session_id)

    worker_runner = AgentRunner("worker", worker_factory, bus)
    worker_runner.start()
    components.runners.append(worker_runner)
    log_fn("Worker agent started.")

    # --- Start indexer ---
    from pearscarf.knowledge import onboarding_summary
    onb_source, onb_chars = onboarding_summary()
    log_fn(f"Onboarding: {onb_chars} chars ({onb_source}).")
    if onb_chars > 8000:
        log_fn(f"Onboarding: {onb_chars} chars exceeds soft budget (~6000 chars / ~1500 tokens).")

    indexer = Indexer()
    indexer.start()
    components.indexer = indexer
    log_fn("Indexer started.")

    # --- Start curator ---
    from pearscarf.curation.curator import Curator
    curator = Curator(log_fn=log_fn)
    curator.start()
    components.curator = curator
    log_fn("Curator started.")

    # --- Start MCP server ---
    mcp_srv = MCPServer()
    mcp_srv.start()
    components.mcp_server = mcp_srv
    log_fn(f"MCP server started on port {MCP_PORT}.")

    return components


def stop_system(components: SystemComponents) -> None:
    """Shut down all running components."""
    if components.mcp_server:
        components.mcp_server.stop()
    if components.curator:
        components.curator.stop()
    if components.indexer:
        components.indexer.stop()
    for runner in components.runners:
        runner.stop()
