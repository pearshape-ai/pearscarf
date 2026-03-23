from __future__ import annotations

from collections.abc import Callable
from typing import Any

import anthropic

from pearscarf.config import ANTHROPIC_API_KEY, MAX_TURNS, MODEL
from pearscarf.tools import ToolRegistry
from pearscarf.tracing import trace_child, trace_span


class BaseAgent:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        system_prompt: str = "",
        agent_name: str = "agent",
        on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
        on_text: Callable[[str], None] | None = None,
        on_tool_result: Callable[[str, str], None] | None = None,
    ) -> None:
        self._client = anthropic.Anthropic(
            api_key=ANTHROPIC_API_KEY or None
        )
        self._registry = tool_registry
        self._messages: list[dict] = []
        self._system_prompt = system_prompt
        self._agent_name = agent_name
        self._on_tool_call = on_tool_call
        self._on_text = on_text
        self._on_tool_result = on_tool_result

    def run(self, user_message: str) -> str:
        self._messages.append({"role": "user", "content": user_message})

        kwargs: dict[str, Any] = {
            "model": MODEL,
            "max_tokens": 4096,
            "messages": self._messages,
        }
        if self._registry.all_schemas():
            kwargs["tools"] = self._registry.all_schemas()
        if self._system_prompt:
            kwargs["system"] = self._system_prompt

        with trace_span(
            f"{self._agent_name}.run",
            run_type="chain",
            metadata={"agent": self._agent_name, "model": MODEL},
            inputs={"user_message": user_message[:500]},
        ) as parent:
            for turn in range(MAX_TURNS):
                with trace_child(
                    parent,
                    f"{self._agent_name}.llm_call",
                    run_type="llm",
                    metadata={"agent": self._agent_name, "turn": turn},
                    inputs={"model": MODEL, "message_count": len(self._messages)},
                ) as llm_span:
                    response = self._client.messages.create(**kwargs)
                    if llm_span:
                        llm_span.end(outputs={
                            "stop_reason": response.stop_reason,
                            "input_tokens": response.usage.input_tokens,
                            "output_tokens": response.usage.output_tokens,
                        })

                self._messages.append(
                    {"role": "assistant", "content": response.content}
                )

                # Emit any text blocks as they come
                for block in response.content:
                    if block.type == "text" and self._on_text:
                        self._on_text(block.text)

                if response.stop_reason == "end_turn":
                    result = self._extract_text(response)
                    if parent:
                        parent.end(outputs={"result": result[:500]})
                    return result

                if response.stop_reason == "tool_use":
                    tool_results = []
                    for block in response.content:
                        if block.type != "tool_use":
                            continue
                        if self._on_tool_call:
                            self._on_tool_call(block.name, block.input)

                        with trace_child(
                            parent,
                            f"tool:{block.name}",
                            run_type="tool",
                            metadata={"agent": self._agent_name, "tool": block.name},
                            inputs=block.input,
                        ) as tool_span:
                            try:
                                result = self._registry.get(block.name).execute(
                                    **block.input
                                )
                            except Exception as exc:
                                result = f"Tool error: {exc}"
                            if tool_span:
                                tool_span.end(outputs={"result": result[:500]})

                        if self._on_tool_result:
                            self._on_tool_result(block.name, result)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result,
                            }
                        )
                    self._messages.append({"role": "user", "content": tool_results})
                else:
                    result = self._extract_text(response)
                    if parent:
                        parent.end(outputs={"result": result[:500]})
                    return result

            if parent:
                parent.end(outputs={"result": "Max turns reached."})
            return "Max turns reached."

    @staticmethod
    def _extract_text(response: anthropic.types.Message) -> str:
        parts = [b.text for b in response.content if b.type == "text"]
        return "\n".join(parts)
