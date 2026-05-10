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
