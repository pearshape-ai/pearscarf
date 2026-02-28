from __future__ import annotations

import json
import threading
import traceback
from collections.abc import Callable
from typing import Any

from pearscaff import log
from pearscaff.agents.base import BaseAgent
from pearscaff.bus import MessageBus


class AgentRunner:
    """Polls the message bus for messages addressed to an agent and dispatches them."""

    def __init__(
        self,
        agent_name: str,
        agent_factory: Callable[[str], BaseAgent],
        bus: MessageBus,
        on_error: Callable[[str, Exception], None] | None = None,
    ) -> None:
        self._agent_name = agent_name
        self._agent_factory = agent_factory
        self._bus = bus
        self._on_error = on_error
        self._agents: dict[str, BaseAgent] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _make_logging_factory(self, session_id: str) -> BaseAgent:
        """Wrap the user-supplied factory so agents get logging callbacks."""
        agent = self._agent_factory(session_id)
        name = self._agent_name

        # Chain: keep any existing callback AND add logging
        orig_on_tool_call = agent._on_tool_call
        orig_on_text = agent._on_text
        orig_on_tool_result = agent._on_tool_result

        def on_tool_call(tool_name: str, args: dict) -> None:
            log.write(name, session_id, "tool", f"{tool_name}({json.dumps(args)})")
            if orig_on_tool_call:
                orig_on_tool_call(tool_name, args)

        def on_text(text: str) -> None:
            log.write(name, session_id, "thinking", text)
            if orig_on_text:
                orig_on_text(text)

        def on_tool_result(tool_name: str, result: str) -> None:
            preview = result[:500] if len(result) > 500 else result
            log.write(name, session_id, "result", f"{tool_name}: {preview}")
            if orig_on_tool_result:
                orig_on_tool_result(tool_name, result)

        agent._on_tool_call = on_tool_call
        agent._on_text = on_text
        agent._on_tool_result = on_tool_result

        return agent

    def _get_agent(self, session_id: str) -> BaseAgent:
        if session_id not in self._agents:
            self._agents[session_id] = self._make_logging_factory(session_id)
        return self._agents[session_id]

    def _process_message(self, msg: dict[str, Any]) -> None:
        session_id = msg["session_id"]
        from_agent = msg["from_agent"]
        content = msg["content"]

        log.write(
            self._agent_name,
            session_id,
            "message_received",
            f"from={from_agent}: {content[:200]}",
        )

        agent = self._get_agent(session_id)

        try:
            # Set session context so agent tools know where to send messages
            if hasattr(agent, "_send_tool") and agent._send_tool:
                agent._send_tool._session_id = session_id
            if hasattr(agent, "_reply_tool") and agent._reply_tool:
                agent._reply_tool._session_id = session_id
                agent._reply_tool._reply_to = from_agent

            # Build context from session history for the agent
            history = self._bus.get_history(session_id)
            agent._messages.clear()
            for h in history:
                if h["from_agent"] == self._agent_name:
                    agent._messages.append(
                        {"role": "assistant", "content": h["content"]}
                    )
                else:
                    agent._messages.append(
                        {"role": "user", "content": h["content"]}
                    )
            # Remove the last message (it's the one we're about to process,
            # and agent.run() will append it)
            if agent._messages and agent._messages[-1]["role"] == "user":
                agent._messages.pop()

            # Run the agent — it uses tools (send_message / reply) to
            # communicate explicitly. No auto-reply from the runner.
            response = agent.run(content)

            log.write(
                self._agent_name,
                session_id,
                "thinking",
                f"agent output (not sent): {response[:200]}",
            )
        except Exception as exc:
            log.write(
                self._agent_name,
                session_id,
                "error",
                f"{type(exc).__name__}: {exc}",
            )
            if self._on_error:
                self._on_error(session_id, exc)
            else:
                traceback.print_exc()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                messages = self._bus.poll(self._agent_name)
                for msg in messages:
                    self._process_message(msg)
            except Exception:
                traceback.print_exc()
            self._stop.wait(1)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, name=f"runner-{self._agent_name}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
