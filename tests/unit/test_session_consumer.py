"""Tests for `pearscarf.session_consumer` — base SessionConsumer dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock

from pearscarf.agents.base import BaseAgent
from pearscarf.session_consumer import SessionConsumer


class _Bot(SessionConsumer):
    name = "bot"

    def _build_agent(self, session_id: str) -> BaseAgent:
        agent = MagicMock(spec=BaseAgent)
        agent._messages = []
        agent.run.return_value = "ok"
        return agent


def _make_bot(bus: MagicMock) -> _Bot:
    ctx = MagicMock()
    return _Bot(ctx=ctx, bus=bus)


def test_get_agent_caches_per_session() -> None:
    bot = _make_bot(MagicMock())
    a1 = bot._get_agent("ses_1")
    a2 = bot._get_agent("ses_1")
    a3 = bot._get_agent("ses_2")
    assert a1 is a2
    assert a1 is not a3


def test_next_pops_pending_then_polls_bus() -> None:
    bus = MagicMock()
    bus.poll.return_value = [{"session_id": "s1", "from_agent": "u", "content": "hi"}]
    bot = _make_bot(bus)
    msg = bot._next()
    assert msg["session_id"] == "s1"
    bus.poll.assert_called_once_with("bot")


def test_next_returns_none_when_bus_empty() -> None:
    bus = MagicMock()
    bus.poll.return_value = []
    bot = _make_bot(bus)
    assert bot._next() is None


def test_handle_rebuilds_history_then_runs_agent() -> None:
    bus = MagicMock()
    bus.get_history.return_value = [
        {"from_agent": "user", "content": "hello"},
        {"from_agent": "bot", "content": "hi back"},
        {"from_agent": "user", "content": "another"},  # last user msg → dropped
    ]
    bot = _make_bot(bus)

    bot._handle({"session_id": "s1", "from_agent": "user", "content": "go"})

    agent = bot._agents["s1"]
    agent.run.assert_called_once_with("go")
    # history rebuild keeps user/assistant alternation, drops trailing user
    assert agent._messages == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi back"},
    ]


def test_session_logging_callbacks_return_three_callables() -> None:
    bot = _make_bot(MagicMock())
    on_call, on_text, on_result = bot._session_logging_callbacks("s1")
    # Should not raise
    on_call("find_entity", {"q": "x"})
    on_text("thinking out loud")
    on_result("find_entity", "result")
