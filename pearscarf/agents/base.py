from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from pearscarf.agents.llm_client import get_llm_client
from pearscarf.config import MAX_TURNS, MODEL
from pearscarf.tools import ToolRegistry
from pearscarf.tracing import trace_child, trace_span
from pearscarf.tracked_call import (
    _run_id_var,
    _turn_index_var,
    mark_run_hit_ceiling,
    tracked_call,
)


class BaseAgent:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        system_prompt: str = "",
        agent_name: str = "agent",
        on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
        on_text: Callable[[str], None] | None = None,
        on_tool_result: Callable[[str, str], None] | None = None,
        max_turns: int | None = None,
    ) -> None:
        self._client = get_llm_client(MODEL)
        self._registry = tool_registry
        self._messages: list[dict] = []
        self._system_prompt = system_prompt
        self._agent_name = agent_name
        self._on_tool_call = on_tool_call
        self._on_text = on_text
        self._on_tool_result = on_tool_result
        # Per-consumer turn ceiling; falls back to global MAX_TURNS when unset.
        self._max_turns = max_turns if max_turns is not None else MAX_TURNS
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def run(self, user_message: str) -> str:
        self._messages.append({"role": "user", "content": user_message})

        invoke_kwargs: dict[str, Any] = {
            "system": self._system_prompt,
            "messages": self._messages,
            "tool_schemas": self._registry.all_schemas(),
            "model": MODEL,
            "max_tokens": 4096,
        }

        run_id = str(uuid.uuid4())
        run_token = _run_id_var.set(run_id)
        try:
            with trace_span(
                f"{self._agent_name}.run",
                run_type="chain",
                metadata={"agent": self._agent_name, "model": MODEL},
                inputs={"user_message": user_message[:500]},
            ) as parent:
                for turn in range(self._max_turns):
                    turn_token = _turn_index_var.set(turn)
                    try:
                        with trace_child(
                            parent,
                            f"{self._agent_name}.llm_call",
                            run_type="llm",
                            metadata={"agent": self._agent_name, "turn": turn},
                            inputs={"model": MODEL, "message_count": len(self._messages)},
                        ) as llm_span:
                            response = tracked_call(
                                self._client,
                                self._agent_name,
                                **invoke_kwargs,
                            )
                            self.total_input_tokens += response.usage.input_tokens
                            self.total_output_tokens += response.usage.output_tokens
                            if llm_span:
                                llm_span.end(
                                    outputs={
                                        "stop_reason": response.stop_reason,
                                        "input_tokens": response.usage.input_tokens,
                                        "output_tokens": response.usage.output_tokens,
                                    }
                                )
                    finally:
                        _turn_index_var.reset(turn_token)

                    # Append assistant message in provider-native shape.
                    self._messages.append(self._client.build_assistant_message(response))

                    # Emit any text as it comes.
                    if response.text and self._on_text:
                        self._on_text(response.text)

                    if response.stop_reason == "end_turn":
                        if parent:
                            parent.end(outputs={"result": response.text[:500]})
                        return response.text

                    if response.stop_reason == "tool_use":
                        tool_outputs: list[tuple[str, str]] = []
                        for tc in response.tool_calls:
                            if self._on_tool_call:
                                self._on_tool_call(tc.name, tc.input)

                            with trace_child(
                                parent,
                                f"tool:{tc.name}",
                                run_type="tool",
                                metadata={"agent": self._agent_name, "tool": tc.name},
                                inputs=tc.input,
                            ) as tool_span:
                                try:
                                    result = self._registry.get(tc.name).execute(**tc.input)
                                except Exception as exc:
                                    result = f"Tool error: {exc}"
                                if tool_span:
                                    tool_span.end(outputs={"result": result[:500]})

                            if self._on_tool_result:
                                self._on_tool_result(tc.name, result)
                            tool_outputs.append((tc.id, result))

                        self._messages.extend(self._client.format_tool_results(tool_outputs))
                    else:
                        if parent:
                            parent.end(outputs={"result": response.text[:500]})
                        return response.text

                # Ceiling hit — flag the last logged turn so dashboards see it.
                mark_run_hit_ceiling(run_id)
                if parent:
                    parent.end(outputs={"result": "Turn ceiling reached."})
                return "Turn ceiling reached."
        finally:
            _run_id_var.reset(run_token)
