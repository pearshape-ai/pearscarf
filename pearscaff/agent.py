from __future__ import annotations

from collections.abc import Callable
from typing import Any

import anthropic

from pearscaff.config import ANTHROPIC_API_KEY, MAX_TURNS, MODEL
from pearscaff.tools import ToolRegistry


class Agent:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._registry = tool_registry
        self._messages: list[dict] = []
        self._on_tool_call = on_tool_call

    def run(self, user_message: str) -> str:
        self._messages.append({"role": "user", "content": user_message})

        for _ in range(MAX_TURNS):
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=4096,
                tools=self._registry.all_schemas(),
                messages=self._messages,
            )

            self._messages.append(
                {"role": "assistant", "content": response.content}
            )

            if response.stop_reason == "end_turn":
                return self._extract_text(response)

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    if self._on_tool_call:
                        self._on_tool_call(block.name, block.input)
                    try:
                        result = self._registry.get(block.name).execute(
                            **block.input
                        )
                    except Exception as exc:
                        result = f"Tool error: {exc}"
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )
                self._messages.append({"role": "user", "content": tool_results})
            else:
                return self._extract_text(response)

        return "Max turns reached."

    @staticmethod
    def _extract_text(response: anthropic.types.Message) -> str:
        parts = [b.text for b in response.content if b.type == "text"]
        return "\n".join(parts)
