"""ExpertBot — generic SessionConsumer for expert bus messages.

Each enabled expert with a `knowledge/agent.md` gets an `ExpertBot`
instance subscribed to `messages WHERE to_agent='<expert_name>'`. The
bot spawns an `ExpertAgent` per session, configured with the expert's
source tools and its domain prompt.

One class — parameterized per instance. No per-expert subclasses:
all expert bots share the same polling / session-caching / dispatch
shape; only the tool set and prompt vary, both of which are data the
expert package already ships.
"""

from __future__ import annotations

from pearscarf.agents.base import BaseAgent
from pearscarf.agents.expert import ExpertAgent
from pearscarf.bus import MessageBus
from pearscarf.expert_context import ExpertContext
from pearscarf.session_consumer import SessionConsumer
from pearscarf.tools import BaseTool, ToolRegistry


class ExpertBot(SessionConsumer):
    """Bus consumer for one expert. Polls `to_agent=<expert_name>` on the bus."""

    def __init__(
        self,
        ctx: ExpertContext,
        bus: MessageBus,
        expert_name: str,
        system_prompt: str,
        tools: list[BaseTool],
        poll_interval: float | None = None,
    ) -> None:
        super().__init__(ctx=ctx, bus=bus, poll_interval=poll_interval)
        # Instance-level `name` shadows Consumer's class default; used by the
        # base class to poll the bus and write logs under the expert's name.
        self.name = expert_name
        self._system_prompt = system_prompt
        self._tools = tools

    def _build_agent(self, session_id: str) -> BaseAgent:
        registry = ToolRegistry()
        for tool in self._tools:
            registry.register(tool)

        on_tool_call, on_text, on_tool_result = self._session_logging_callbacks(session_id)
        return ExpertAgent(
            ctx=self._ctx,
            domain_prompt=self._system_prompt,
            tool_registry=registry,
            on_tool_call=on_tool_call,
            on_text=on_text,
            on_tool_result=on_tool_result,
        )
