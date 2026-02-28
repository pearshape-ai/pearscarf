from __future__ import annotations

import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

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

    def _get_agent(self, session_id: str) -> BaseAgent:
        if session_id not in self._agents:
            self._agents[session_id] = self._agent_factory(session_id)
        return self._agents[session_id]

    def _process_message(self, msg: dict[str, Any]) -> None:
        session_id = msg["session_id"]
        from_agent = msg["from_agent"]
        content = msg["content"]

        agent = self._get_agent(session_id)

        try:
            # Build context from session history for the agent
            history = self._bus.get_history(session_id)
            # Rebuild the agent's message history from the session
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

            response = agent.run(content)

            self._bus.send(
                session_id=session_id,
                from_agent=self._agent_name,
                to_agent=from_agent,
                content=response,
                reasoning=f"Response to message from {from_agent}",
            )
        except Exception as exc:
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
