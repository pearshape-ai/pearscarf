"""Tests for pure helpers in `pearscarf.agents.llm_client`:
`resolve_provider`, `_normalize_anthropic_stop`, `_normalize_openai_stop`.
"""

from __future__ import annotations

import pytest

from pearscarf.agents.llm_client import (
    _normalize_anthropic_stop,
    _normalize_openai_stop,
    resolve_provider,
)

# ---- resolve_provider ----


def test_resolve_provider_claude_prefix_routes_to_anthropic() -> None:
    assert resolve_provider("claude-opus-4-7") == "anthropic"


def test_resolve_provider_gpt_prefix_routes_to_openai() -> None:
    assert resolve_provider("gpt-5-turbo") == "openai"


def test_resolve_provider_o_series_routes_to_openai() -> None:
    assert resolve_provider("o1-preview") == "openai"
    assert resolve_provider("o3-mini") == "openai"
    assert resolve_provider("o4-mini") == "openai"


def test_resolve_provider_explicit_overrides_model_prefix() -> None:
    assert resolve_provider("claude-opus-4-7", "openai") == "openai"
    assert resolve_provider("gpt-5", "anthropic") == "anthropic"


def test_resolve_provider_unknown_explicit_raises() -> None:
    with pytest.raises(ValueError, match="not supported"):
        resolve_provider("claude-opus-4-7", "azure")


def test_resolve_provider_unknown_model_prefix_raises() -> None:
    with pytest.raises(ValueError, match="Cannot infer provider"):
        resolve_provider("llama-3-70b")


# ---- _normalize_anthropic_stop ----


def test_normalize_anthropic_passes_through_canonical_values() -> None:
    assert _normalize_anthropic_stop("end_turn") == "end_turn"
    assert _normalize_anthropic_stop("tool_use") == "tool_use"
    assert _normalize_anthropic_stop("max_tokens") == "max_tokens"


def test_normalize_anthropic_none_becomes_unknown() -> None:
    assert _normalize_anthropic_stop(None) == "unknown"


def test_normalize_anthropic_passes_through_unrecognized_strings() -> None:
    assert _normalize_anthropic_stop("weird_stop") == "weird_stop"


# ---- _normalize_openai_stop ----


def test_normalize_openai_maps_stop_to_end_turn() -> None:
    assert _normalize_openai_stop("stop") == "end_turn"


def test_normalize_openai_maps_tool_calls_to_tool_use() -> None:
    assert _normalize_openai_stop("tool_calls") == "tool_use"


def test_normalize_openai_maps_length_to_max_tokens() -> None:
    assert _normalize_openai_stop("length") == "max_tokens"


def test_normalize_openai_none_becomes_unknown() -> None:
    assert _normalize_openai_stop(None) == "unknown"


def test_normalize_openai_unmapped_passes_through() -> None:
    assert _normalize_openai_stop("content_filter") == "content_filter"


# ---- AnthropicClient.invoke ----


from pearscarf.agents.llm_client import AnthropicClient, OpenAIClient  # noqa: E402


def _make_anthropic_client(mock_anthropic_client) -> AnthropicClient:
    client = AnthropicClient.__new__(AnthropicClient)
    client._client = mock_anthropic_client
    return client


def _make_openai_client(mock_openai_client) -> OpenAIClient:
    client = OpenAIClient.__new__(OpenAIClient)
    client._client = mock_openai_client
    return client


def test_anthropic_invoke_request_shape_with_system_and_tools(
    mock_anthropic_client, anthropic_response_factory
) -> None:
    client = _make_anthropic_client(mock_anthropic_client)
    mock_anthropic_client.messages.create.return_value = anthropic_response_factory.response()

    client.invoke(
        system="You are an extractor.",
        messages=[{"role": "user", "content": "hi"}],
        tool_schemas=[{"name": "save", "description": "x", "input_schema": {}}],
        model="claude-opus-4-7",
        max_tokens=4096,
    )
    kwargs = mock_anthropic_client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-opus-4-7"
    assert kwargs["max_tokens"] == 4096
    # System turned into list-of-blocks with cache_control
    assert isinstance(kwargs["system"], list)
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    # Last tool gets cache_control
    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_anthropic_invoke_omits_system_when_blank(
    mock_anthropic_client, anthropic_response_factory
) -> None:
    client = _make_anthropic_client(mock_anthropic_client)
    mock_anthropic_client.messages.create.return_value = anthropic_response_factory.response()

    client.invoke(
        system="",
        messages=[{"role": "user", "content": "hi"}],
        tool_schemas=[],
        model="claude-opus-4-7",
        max_tokens=512,
    )
    kwargs = mock_anthropic_client.messages.create.call_args.kwargs
    assert "system" not in kwargs
    assert "tools" not in kwargs


def test_anthropic_invoke_normalizes_text_and_tool_blocks(
    mock_anthropic_client, anthropic_response_factory
) -> None:
    client = _make_anthropic_client(mock_anthropic_client)
    mock_anthropic_client.messages.create.return_value = anthropic_response_factory.response(
        content=[
            anthropic_response_factory.text_block("hello "),
            anthropic_response_factory.text_block("world"),
            anthropic_response_factory.tool_block("tu_1", "save", {"x": 1}),
        ],
        stop_reason="tool_use",
        input_tokens=42,
        output_tokens=7,
        cache_creation=11,
        cache_read=3,
    )

    resp = client.invoke(
        system="s",
        messages=[],
        tool_schemas=[],
        model="claude-opus-4-7",
        max_tokens=128,
    )
    assert resp.text == "hello \nworld"
    assert resp.stop_reason == "tool_use"
    assert resp.tool_calls[0].id == "tu_1"
    assert resp.tool_calls[0].name == "save"
    assert resp.tool_calls[0].input == {"x": 1}
    assert resp.usage.input_tokens == 42
    assert resp.usage.output_tokens == 7
    assert resp.usage.cache_creation_tokens == 11
    assert resp.usage.cache_read_tokens == 3


# ---- OpenAIClient.invoke ----


def test_openai_invoke_uses_max_completion_tokens_for_gpt5(
    mock_openai_client, openai_response_factory
) -> None:
    client = _make_openai_client(mock_openai_client)
    mock_openai_client.chat.completions.create.return_value = openai_response_factory.response()

    client.invoke(
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        tool_schemas=[],
        model="gpt-5-turbo",
        max_tokens=1024,
    )
    kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
    assert "max_completion_tokens" in kwargs
    assert kwargs["max_completion_tokens"] == 1024
    assert "max_tokens" not in kwargs


def test_openai_invoke_uses_max_tokens_for_gpt4(
    mock_openai_client, openai_response_factory
) -> None:
    client = _make_openai_client(mock_openai_client)
    mock_openai_client.chat.completions.create.return_value = openai_response_factory.response()

    client.invoke(
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        tool_schemas=[],
        model="gpt-4-turbo",
        max_tokens=1024,
    )
    kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
    assert kwargs.get("max_tokens") == 1024


def test_openai_invoke_includes_system_message_first(
    mock_openai_client, openai_response_factory
) -> None:
    client = _make_openai_client(mock_openai_client)
    mock_openai_client.chat.completions.create.return_value = openai_response_factory.response()

    client.invoke(
        system="You are X.",
        messages=[{"role": "user", "content": "hi"}],
        tool_schemas=[],
        model="gpt-5-turbo",
        max_tokens=128,
    )
    msgs = mock_openai_client.chat.completions.create.call_args.kwargs["messages"]
    assert msgs[0] == {"role": "system", "content": "You are X."}
    assert msgs[1] == {"role": "user", "content": "hi"}


def test_openai_invoke_remaps_tool_schemas(mock_openai_client, openai_response_factory) -> None:
    client = _make_openai_client(mock_openai_client)
    mock_openai_client.chat.completions.create.return_value = openai_response_factory.response()

    client.invoke(
        system="",
        messages=[],
        tool_schemas=[
            {"name": "save", "description": "save it", "input_schema": {"type": "object"}},
        ],
        model="gpt-5-turbo",
        max_tokens=128,
    )
    tools = mock_openai_client.chat.completions.create.call_args.kwargs["tools"]
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "save"
    assert tools[0]["function"]["parameters"] == {"type": "object"}


def test_openai_invoke_normalizes_response_with_tool_calls(
    mock_openai_client, openai_response_factory
) -> None:
    client = _make_openai_client(mock_openai_client)
    mock_openai_client.chat.completions.create.return_value = openai_response_factory.response(
        text="some text",
        tool_calls=[openai_response_factory.tool_call("tc1", "save", '{"x": 1}')],
        finish_reason="tool_calls",
        prompt_tokens=100,
        completion_tokens=20,
        cached_tokens=80,
    )

    resp = client.invoke(
        system="", messages=[], tool_schemas=[], model="gpt-5-turbo", max_tokens=128
    )
    assert resp.text == "some text"
    assert resp.stop_reason == "tool_use"
    assert resp.tool_calls[0].id == "tc1"
    assert resp.tool_calls[0].name == "save"
    assert resp.tool_calls[0].input == {"x": 1}
    # input_tokens = prompt_tokens - cached
    assert resp.usage.input_tokens == 20
    assert resp.usage.cache_read_tokens == 80


def test_openai_invoke_handles_malformed_tool_arguments_as_empty_dict(
    mock_openai_client, openai_response_factory
) -> None:
    client = _make_openai_client(mock_openai_client)
    mock_openai_client.chat.completions.create.return_value = openai_response_factory.response(
        text="x",
        tool_calls=[openai_response_factory.tool_call("tc1", "save", "not-json")],
        finish_reason="tool_calls",
    )
    resp = client.invoke(
        system="", messages=[], tool_schemas=[], model="gpt-5-turbo", max_tokens=64
    )
    assert resp.tool_calls[0].input == {}


# ---- build_assistant_message / format_tool_results ----


def test_anthropic_build_assistant_message_reuses_raw_content(
    mock_anthropic_client, anthropic_response_factory
) -> None:
    client = _make_anthropic_client(mock_anthropic_client)
    raw = anthropic_response_factory.response()
    mock_anthropic_client.messages.create.return_value = raw

    resp = client.invoke(
        system="", messages=[], tool_schemas=[], model="claude-opus-4-7", max_tokens=64
    )
    msg = client.build_assistant_message(resp)
    assert msg["role"] == "assistant"
    assert msg["content"] is raw.content


def test_anthropic_format_tool_results_returns_user_message_with_blocks() -> None:
    client = AnthropicClient.__new__(AnthropicClient)
    out = client.format_tool_results([("tu1", "ok"), ("tu2", "fail")])
    assert len(out) == 1
    assert out[0]["role"] == "user"
    blocks = out[0]["content"]
    assert blocks[0]["tool_use_id"] == "tu1"
    assert blocks[1]["tool_use_id"] == "tu2"


def test_openai_format_tool_results_returns_one_message_per_result() -> None:
    client = OpenAIClient.__new__(OpenAIClient)
    out = client.format_tool_results([("tc1", "ok"), ("tc2", "fail")])
    assert out == [
        {"role": "tool", "tool_call_id": "tc1", "content": "ok"},
        {"role": "tool", "tool_call_id": "tc2", "content": "fail"},
    ]
