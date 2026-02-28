from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pearscaff import log
from pearscaff.agents.base import BaseAgent
from pearscaff.bus import MessageBus
from pearscaff.knowledge import KnowledgeStore
from pearscaff.tools import BaseTool, ToolRegistry


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


class SaveKnowledgeTool(BaseTool):
    name = "save_knowledge"
    description = (
        "Save a piece of knowledge about how to operate this domain. "
        "Use this to record useful selectors, navigation patterns, timing info, "
        "or any insight that will help you work more effectively next time."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Short slug for the knowledge file, e.g. 'inbox-selectors' or 'mark-as-read-flow'",
            },
            "content": {
                "type": "string",
                "description": "The knowledge content in markdown format",
            },
        },
        "required": ["name", "content"],
    }

    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    def execute(self, **kwargs: Any) -> str:
        name = kwargs["name"]
        content = kwargs["content"]
        self._store.save(name, content)
        return f"Knowledge saved as '{name}'."


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
        self._knowledge = KnowledgeStore(domain)

        # Register the save_knowledge tool
        tool_registry.register(SaveKnowledgeTool(self._knowledge))

        # Register reply tool if bus is provided
        self._reply_tool: ReplyTool | None = None
        if bus:
            self._reply_tool = ReplyTool(bus, agent_name or domain)
            tool_registry.register(self._reply_tool)

        # Build system prompt with knowledge
        system_prompt = self._build_system_prompt(domain_prompt)

        super().__init__(
            tool_registry=tool_registry,
            system_prompt=system_prompt,
            on_tool_call=on_tool_call,
            on_text=on_text,
            on_tool_result=on_tool_result,
        )

    def _build_system_prompt(self, domain_prompt: str) -> str:
        parts = [domain_prompt]

        if self._knowledge.has_knowledge():
            parts.append(
                "\n\n## Your accumulated knowledge\n\n"
                "The following is knowledge you have collected from previous sessions. "
                "Use it to operate more effectively.\n\n"
                + self._knowledge.load_all()
            )
        else:
            parts.append(
                "\n\nYou have no accumulated knowledge yet. "
                "As you work, use the save_knowledge tool to record useful "
                "information that will help you in future sessions."
            )

        return "\n".join(parts)
