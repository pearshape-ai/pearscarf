from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pearscarf import log
from pearscarf.agents.base import BaseAgent
from pearscarf.bus import MessageBus
from pearscarf.tools import BaseTool, ToolRegistry


class ReplyTool(BaseTool):
    """Experts use this to send results back to the requesting agent."""

    name = "reply"
    description = (
        "Send your response back to the agent that requested this work. "
        "You MUST use this tool to deliver your results — your text output "
        "is only logged internally and nobody sees it unless you use reply."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Your response content with the results of your work",
            },
        },
        "required": ["content"],
    }

    def __init__(self, bus: MessageBus, agent_name: str) -> None:
        self._bus = bus
        self._agent_name = agent_name
        self._session_id: str | None = None
        self._reply_to: str | None = None

    def execute(self, **kwargs: Any) -> str:
        content = kwargs["content"]
        if not self._session_id or not self._reply_to:
            return "Error: no active session or reply target set."
        self._bus.send(
            session_id=self._session_id,
            from_agent=self._agent_name,
            to_agent=self._reply_to,
            content=content,
            reasoning=f"Reply to {self._reply_to}",
        )
        log.write(
            self._agent_name,
            self._session_id,
            "message_sent",
            f"to={self._reply_to}: {content[:200]}",
        )
        return f"Reply sent to {self._reply_to}."


class ExpertAgent(BaseAgent):
    def __init__(
        self,
        domain: str,
        domain_prompt: str,
        tool_registry: ToolRegistry,
        bus: MessageBus | None = None,
        agent_name: str = "",
        on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
        on_text: Callable[[str], None] | None = None,
        on_tool_result: Callable[[str, str], None] | None = None,
    ) -> None:
        # Register reply tool if bus is provided
        self._reply_tool: ReplyTool | None = None
        if bus:
            self._reply_tool = ReplyTool(bus, agent_name or domain)
            tool_registry.register(self._reply_tool)

        super().__init__(
            tool_registry=tool_registry,
            system_prompt=domain_prompt,
            agent_name=agent_name or domain,
            on_tool_call=on_tool_call,
            on_text=on_text,
            on_tool_result=on_tool_result,
        )
