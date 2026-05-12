"""Tests for `pearscarf.storage.neo4j_client` — connection wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pearscarf.storage import neo4j_client


@pytest.fixture(autouse=True)
def _restore_driver() -> None:
    yield
    neo4j_client._driver = None


def test_get_driver_returns_cached_driver_on_second_call() -> None:
    fake_driver = MagicMock()
    neo4j_client._driver = fake_driver
    assert neo4j_client.get_driver() is fake_driver


def test_get_driver_lazy_inits_via_GraphDatabase_driver() -> None:
    neo4j_client._driver = None
    with patch("pearscarf.storage.neo4j_client.GraphDatabase") as gdb:
        gdb.driver.return_value = "FAKE_DRIVER"
        result = neo4j_client.get_driver()

    gdb.driver.assert_called_once()
    assert result == "FAKE_DRIVER"
    assert neo4j_client._driver == "FAKE_DRIVER"


def test_get_driver_disables_unrecognized_notifications() -> None:
    """Driver init must opt out of UNRECOGNIZED-classification notifications.

    Without this, every `MATCH (n:Label)` against a label with zero nodes
    logs a WARNING — floods output on empty/wiped graphs.
    """
    from neo4j import NotificationDisabledClassification

    neo4j_client._driver = None
    with patch("pearscarf.storage.neo4j_client.GraphDatabase") as gdb:
        gdb.driver.return_value = "FAKE_DRIVER"
        neo4j_client.get_driver()

    kwargs = gdb.driver.call_args.kwargs
    assert NotificationDisabledClassification.UNRECOGNIZED in kwargs.get(
        "notifications_disabled_classifications", []
    )


def test_close_resets_driver_and_invokes_close() -> None:
    fake_driver = MagicMock()
    neo4j_client._driver = fake_driver
    neo4j_client.close()
    fake_driver.close.assert_called_once()
    assert neo4j_client._driver is None


def test_close_no_op_when_uninitialized() -> None:
    neo4j_client._driver = None
    neo4j_client.close()
    assert neo4j_client._driver is None
