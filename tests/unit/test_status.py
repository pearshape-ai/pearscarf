"""Tests for `pearscarf.status` — agent activity registry."""

from __future__ import annotations

import pytest

from pearscarf import status


@pytest.fixture(autouse=True)
def _clear_activity() -> None:
    status._activity.clear()


def test_set_status_records_active_agent() -> None:
    status.set_status("triage", "ses_001", "processing record_1")
    assert status.get_activity("ses_001") is not None
    agent, text, elapsed = status.get_activity("ses_001")
    assert agent == "triage"
    assert text == "processing record_1"
    assert elapsed >= 0


def test_clear_status_removes_active_agent() -> None:
    status.set_status("triage", "ses_001", "x")
    status.clear_status("triage", "ses_001")
    assert status.get_activity("ses_001") is None


def test_get_activity_returns_none_for_unknown_session() -> None:
    assert status.get_activity("missing") is None


def test_get_activity_picks_latest_when_multiple_agents_active() -> None:
    import time as _time

    status.set_status("triage", "ses_x", "first")
    _time.sleep(0.001)  # ensure monotonic ordering
    status.set_status("extraction", "ses_x", "second")
    agent, text, _ = status.get_activity("ses_x")
    assert agent == "extraction"
    assert text == "second"
