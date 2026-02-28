from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pearscaff.agents.base import BaseAgent
from pearscaff.knowledge import KnowledgeStore
from pearscaff.tools import BaseTool, ToolRegistry


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
        on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
        on_text: Callable[[str], None] | None = None,
        on_tool_result: Callable[[str, str], None] | None = None,
    ) -> None:
        self._knowledge = KnowledgeStore(domain)

        # Register the save_knowledge tool
        tool_registry.register(SaveKnowledgeTool(self._knowledge))

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
