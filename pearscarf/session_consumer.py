"""SessionConsumer — base for bus consumers that maintain per-session agents.

Bus-side consumers (`Assistant`, `ExpertBot`) share a common shape: poll a
bus target, buffer the batch, route each message to a per-session agent
(lazily built + cached), and rebuild the session's conversation history
from the bus before each LLM turn.

Subclasses override `_build_agent(session_id)` to return the concrete
per-session agent — configured with that consumer's tools + prompt.
Everything else lives here.
"""

from __future__ import annotations

import json
from abc import abstractmethod

from pearscarf import log, status
from pearscarf.agents.base import BaseAgent
from pearscarf.bus import MessageBus
from pearscarf.consumer import Consumer
from pearscarf.expert_context import ExpertContext
from pearscarf.tracing import trace_span
from pearscarf.tracked_call import _session_id_var


class SessionConsumer(Consumer):
    """Consumer that polls a bus target and dispatches per-session agents."""

    default_poll_interval = 1.0

    def __init__(
        self,
        ctx: ExpertContext,
        bus: MessageBus,
        poll_interval: float | None = None,
    ) -> None:
        super().__init__(poll_interval=poll_interval)
        self._ctx = ctx
        self._bus = bus
        self._agents: dict[str, BaseAgent] = {}
        self._pending: list = []

    @abstractmethod
    def _build_agent(self, session_id: str) -> BaseAgent:
        """Build a new per-session agent. Called once per session, cached after."""

    # --- Consumer hooks ---

    def _next(self):
        if self._pending:
            return self._pending.pop(0)
        messages = self._bus.poll(self.name)
        if not messages:
            return None
        self._pending = list(messages)
        return self._pending.pop(0) if self._pending else None

    def _handle(self, msg: dict) -> None:
        session_id = msg["session_id"]
        from_agent = msg["from_agent"]
        content = msg["content"]

        log.write(
            self.name,
            session_id,
            "message_received",
            f"from={from_agent}: {content[:200]}",
        )

        session_token = _session_id_var.set(session_id)
        agent = self._get_agent(session_id)
        status.set_status(self.name, session_id, "working")
        try:
            with trace_span(
                f"{self.name}.process_message",
                run_type="chain",
                metadata={
                    "agent": self.name,
                    "session_id": session_id,
                    "from_agent": from_agent,
                },
                inputs={"content": content[:500]},
            ) as span:
                # Per-message session context for tools that need it
                if hasattr(agent, "_send_tool") and agent._send_tool:
                    agent._send_tool._session_id = session_id
                if hasattr(agent, "_reply_tool") and agent._reply_tool:
                    agent._reply_tool._session_id = session_id
                    agent._reply_tool._reply_to = from_agent

                # Rebuild conversation history for this session
                history = self._bus.get_history(session_id)
                agent._messages.clear()
                for h in history:
                    if h["from_agent"] == self.name:
                        agent._messages.append({"role": "assistant", "content": h["content"]})
                    else:
                        agent._messages.append({"role": "user", "content": h["content"]})
                # Drop the last user message — agent.run(content) will append it
                if agent._messages and agent._messages[-1]["role"] == "user":
                    agent._messages.pop()

                response = agent.run(content)

                log.write(
                    self.name,
                    session_id,
                    "thinking",
                    f"agent output (not sent): {response[:200]}",
                )
                if span:
                    span.end(outputs={"response": response[:500]})
        finally:
            status.clear_status(self.name, session_id)
            _session_id_var.reset(session_token)

    # --- Per-session agent cache ---

    def _get_agent(self, session_id: str) -> BaseAgent:
        if session_id not in self._agents:
            self._agents[session_id] = self._build_agent(session_id)
        return self._agents[session_id]

    # --- Logging callbacks (shared by subclasses) ---

    def _session_logging_callbacks(self, session_id: str):
        """Return (on_tool_call, on_text, on_tool_result) logging callbacks."""

        def on_tool_call(tool_name: str, args: dict) -> None:
            log.write(self.name, session_id, "tool", f"{tool_name}({json.dumps(args)})")

        def on_text(text: str) -> None:
            log.write(self.name, session_id, "thinking", text)

        def on_tool_result(tool_name: str, result: str) -> None:
            preview = result[:500] if len(result) > 500 else result
            log.write(self.name, session_id, "result", f"{tool_name}: {preview}")

        return on_tool_call, on_text, on_tool_result
