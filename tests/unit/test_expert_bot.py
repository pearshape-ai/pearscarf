"""Tests for `pearscarf.expert_bot` — generic SessionConsumer wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pearscarf.expert_bot import ExpertBot
from pearscarf.tools import BaseTool


class _Tool(BaseTool):
    name = "noop"
    description = "noop"
    input_schema: dict = {"type": "object", "properties": {}}

    def execute(self, **_kwargs) -> str:
        return ""


def _bot() -> ExpertBot:
    ctx = MagicMock()
    bus = MagicMock()
    return ExpertBot(
        ctx=ctx,
        bus=bus,
        expert_name="linearscarf",
        system_prompt="You are linearscarf.",
        tools=[_Tool()],
    )


def test_expert_bot_name_set_to_expert_name() -> None:
    bot = _bot()
    assert bot.name == "linearscarf"


def test_expert_bot_build_agent_uses_provided_tools_and_prompt() -> None:
    bot = _bot()
    with patch("pearscarf.expert_bot.ExpertAgent") as MockAgent:
        bot._build_agent("ses_001")
    MockAgent.assert_called_once()
    kwargs = MockAgent.call_args.kwargs
    assert kwargs["domain_prompt"] == "You are linearscarf."
    assert kwargs["max_turns"] == ExpertBot.max_turns
