"""Provider-agnostic LLM client layer.

`BaseAgent` talks to an `LLMClient` instance; concrete clients (Anthropic,
OpenAI) hide the per-provider differences in tool schema shape, tool-result
message shape, system-prompt placement, and prompt-caching mechanics. New
providers drop in here without touching agent code.

Selection:
    - Explicit `PROVIDER` env var wins (set to "anthropic" or "openai").
    - Otherwise, inferred from the model string: `claude-*` → anthropic,
      `gpt-*` / `o1-*` / `o3-*` / `o4-*` → openai.
    - Unknown → error with a clear message listing supported prefixes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic
from openai import OpenAI

from pearscarf.config import ANTHROPIC_API_KEY, OPENAI_API_KEY, PROVIDER

# ------------ Normalized response shapes ------------


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass
class LLMToolCall:
    id: str  # provider-native tool-call id (Anthropic's block.id, OpenAI's tool_call.id)
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text: str  # concatenated text content
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    stop_reason: str = ""  # normalized: end_turn | tool_use | max_tokens | error
    usage: LLMUsage = field(default_factory=LLMUsage)
    raw: Any = None  # provider-native response, for debugging


# ------------ Client protocol ------------


class LLMClient(Protocol):
    provider_name: str

    def invoke(
        self,
        *,
        system: str,
        messages: list[dict],
        tool_schemas: list[dict],
        model: str,
        max_tokens: int,
    ) -> LLMResponse: ...

    def build_assistant_message(self, response: LLMResponse) -> dict:
        """Build the provider-native assistant message to append to history."""

    def format_tool_results(self, results: list[tuple[str, str]]) -> list[dict]:
        """Return one or more provider-native messages carrying tool outputs.

        Anthropic returns a single user message with a list of tool_result
        blocks; OpenAI returns one `role=tool` message per result. Always
        return a list so the caller can `.extend()` the history.
        """


# ------------ Anthropic ------------


class AnthropicClient:
    provider_name = "anthropic"

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(
            api_key=ANTHROPIC_API_KEY or None,
            max_retries=3,
        )

    def invoke(
        self,
        *,
        system: str,
        messages: list[dict],
        tool_schemas: list[dict],
        model: str,
        max_tokens: int,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if tool_schemas:
            # Mark the last tool schema for prompt caching — tools + system
            # become the cacheable prefix.
            tools = [dict(t) for t in tool_schemas]
            tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
            kwargs["tools"] = tools
        if system:
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        resp = self._client.messages.create(**kwargs)

        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    LLMToolCall(id=block.id, name=block.name, input=dict(block.input))
                )

        usage = resp.usage
        return LLMResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=_normalize_anthropic_stop(resp.stop_reason),
            usage=LLMUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", None) or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", None) or 0,
            ),
            raw=resp,
        )

    def build_assistant_message(self, response: LLMResponse) -> dict:
        # Reuse the raw content blocks so round-trip is lossless.
        return {"role": "assistant", "content": response.raw.content}

    def format_tool_results(self, results: list[tuple[str, str]]) -> list[dict]:
        return [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
                    for tool_use_id, content in results
                ],
            }
        ]


def _normalize_anthropic_stop(s: str | None) -> str:
    if s in ("end_turn", "tool_use", "max_tokens"):
        return s
    return s or "unknown"


# ------------ OpenAI ------------


class OpenAIClient:
    provider_name = "openai"

    def __init__(self) -> None:
        self._client = OpenAI(api_key=OPENAI_API_KEY or None)

    def invoke(
        self,
        *,
        system: str,
        messages: list[dict],
        tool_schemas: list[dict],
        model: str,
        max_tokens: int,
    ) -> LLMResponse:
        # OpenAI wants the system prompt inline as the first message. Prompt
        # caching is automatic for prefixes ≥1024 tokens — no cache_control
        # markers to add (or strip; none are present in `messages` since we
        # build history in normalized Anthropic-agnostic form).
        chat_messages: list[dict] = []
        if system:
            chat_messages.append({"role": "system", "content": system})
        chat_messages.extend(messages)

        # gpt-5* and o-series use `max_completion_tokens`; gpt-4* family uses `max_tokens`.
        token_kwarg = (
            "max_completion_tokens"
            if model.startswith(("gpt-5", "o1", "o3", "o4"))
            else "max_tokens"
        )
        kwargs: dict[str, Any] = {
            "model": model,
            token_kwarg: max_tokens,
            "messages": chat_messages,
        }
        if tool_schemas:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tool_schemas
            ]
        resp = self._client.chat.completions.create(**kwargs)

        choice = resp.choices[0]
        msg = choice.message
        tool_calls: list[LLMToolCall] = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(LLMToolCall(id=tc.id, name=tc.function.name, input=args))

        usage = resp.usage
        cache_read = 0
        if getattr(usage, "prompt_tokens_details", None) is not None:
            cache_read = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0

        return LLMResponse(
            text=msg.content or "",
            tool_calls=tool_calls,
            stop_reason=_normalize_openai_stop(choice.finish_reason),
            usage=LLMUsage(
                # prompt_tokens on OpenAI includes cached; subtract to report
                # "fresh" input tokens consistently with Anthropic's shape.
                input_tokens=(usage.prompt_tokens or 0) - cache_read,
                output_tokens=usage.completion_tokens or 0,
                cache_creation_tokens=0,  # OpenAI doesn't separate this out
                cache_read_tokens=cache_read,
            ),
            raw=resp,
        )

    def build_assistant_message(self, response: LLMResponse) -> dict:
        # OpenAI's assistant message shape includes tool_calls inline.
        msg: dict[str, Any] = {"role": "assistant", "content": response.text or None}
        if response.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.input)},
                }
                for tc in response.tool_calls
            ]
        return msg

    def format_tool_results(self, results: list[tuple[str, str]]) -> list[dict]:
        return [
            {"role": "tool", "tool_call_id": tool_use_id, "content": content}
            for tool_use_id, content in results
        ]


def _normalize_openai_stop(s: str | None) -> str:
    return {
        "stop": "end_turn",
        "tool_calls": "tool_use",
        "length": "max_tokens",
    }.get(s or "", s or "unknown")


# ------------ Selection ------------


_PROVIDER_PREFIXES = {
    "claude": "anthropic",
    "gpt": "openai",
    "o1": "openai",
    "o3": "openai",
    "o4": "openai",
}


def resolve_provider(model: str, explicit: str = "") -> str:
    """Return 'anthropic' or 'openai'. Raise on unknown."""
    if explicit:
        if explicit not in ("anthropic", "openai"):
            raise ValueError(
                f"PROVIDER={explicit!r} is not supported. Use 'anthropic' or 'openai'."
            )
        return explicit
    head = model.split("-", 1)[0].lower()
    provider = _PROVIDER_PREFIXES.get(head)
    if provider is None:
        raise ValueError(
            f"Cannot infer provider from MODEL={model!r}. "
            f"Known prefixes: {sorted(_PROVIDER_PREFIXES)}. "
            f"Set PROVIDER=anthropic|openai to override."
        )
    return provider


def get_llm_client(model: str, explicit_provider: str = "") -> LLMClient:
    provider = resolve_provider(model, explicit_provider or PROVIDER)
    if provider == "anthropic":
        return AnthropicClient()
    return OpenAIClient()
