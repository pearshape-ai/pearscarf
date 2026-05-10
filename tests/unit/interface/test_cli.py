"""Tests for `pearscarf.interface.cli` — Click command surfaces.

Uses Click's `CliRunner` to invoke the top-level command group. Mocks at
the import path the CLI uses (since each command imports collaborators
inside its body, not at module level).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from pearscarf.interface.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---- top-level ----


def test_version_flag_prints_pearscarf_version(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "PearScarf v" in result.output


def test_no_args_shows_help(runner: CliRunner) -> None:
    result = runner.invoke(cli, [])
    assert "Usage:" in result.output


# ---- mcp ----


def test_mcp_no_subcommand_prints_hint(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["mcp"])
    assert "psc mcp start" in result.output


def test_mcp_start_initializes_records_then_runs_server(runner: CliRunner) -> None:
    fake_server = MagicMock()
    fake_registry = MagicMock()
    fake_registry.get_by_name.return_value = None  # skip records init branch
    with (
        patch("pearscarf.mcp.mcp_server.MCPServer", return_value=fake_server),
        patch("pearscarf.registry.get_registry", return_value=fake_registry),
    ):
        result = runner.invoke(cli, ["mcp", "start"])
    assert result.exit_code == 0
    fake_server.run_foreground.assert_called_once()


def test_mcp_status_lists_keys(runner: CliRunner) -> None:
    with (
        patch("pearscarf.storage.db.init_db"),
        patch(
            "pearscarf.storage.store.list_mcp_keys",
            return_value=[{"revoked": False}, {"revoked": True}],
        ),
    ):
        result = runner.invoke(cli, ["mcp", "status"])
    assert result.exit_code == 0
    assert "1 active, 2 total" in result.output


def test_mcp_keys_create_prints_raw_key(runner: CliRunner) -> None:
    with (
        patch("pearscarf.storage.db.init_db"),
        patch(
            "pearscarf.storage.store.create_mcp_key",
            return_value={"id": "mck_001", "name": "ci", "raw_key": "psk_ABC"},
        ),
    ):
        result = runner.invoke(cli, ["mcp", "keys", "create", "--name", "ci"])
    assert result.exit_code == 0
    assert "psk_ABC" in result.output
    assert "mck_001" in result.output


def test_mcp_keys_revoke_reports_success(runner: CliRunner) -> None:
    with (
        patch("pearscarf.storage.db.init_db"),
        patch("pearscarf.storage.store.revoke_mcp_key", return_value=True),
    ):
        result = runner.invoke(cli, ["mcp", "keys", "revoke", "mck_001"])
    assert "revoked" in result.output


def test_mcp_keys_revoke_reports_not_found(runner: CliRunner) -> None:
    with (
        patch("pearscarf.storage.db.init_db"),
        patch("pearscarf.storage.store.revoke_mcp_key", return_value=False),
    ):
        result = runner.invoke(cli, ["mcp", "keys", "revoke", "mck_999"])
    assert "not found" in result.output


# ---- triage / extraction / assistant / curation ----


def test_triage_no_subcommand_prints_hint(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["triage"])
    assert "psc triage start" in result.output


def test_triage_start_invokes_run_foreground(runner: CliRunner) -> None:
    fake_triage = MagicMock()
    with patch("pearscarf.triage.Triage", return_value=fake_triage):
        result = runner.invoke(cli, ["triage", "start"])
    assert result.exit_code == 0
    fake_triage.run_foreground.assert_called_once()


def test_extraction_start_default_no_debug_dir(runner: CliRunner) -> None:
    fake_ext = MagicMock()
    with patch("pearscarf.extraction.Extraction", return_value=fake_ext) as Ext:
        result = runner.invoke(cli, ["extraction", "start"])
    assert result.exit_code == 0
    Ext.assert_called_once_with(debug_dir=None)
    fake_ext.run_foreground.assert_called_once()


def test_extraction_start_with_debug_sets_debug_dir(runner: CliRunner) -> None:
    fake_ext = MagicMock()
    with patch("pearscarf.extraction.Extraction", return_value=fake_ext) as Ext:
        result = runner.invoke(cli, ["extraction", "start", "--debug"])
    assert result.exit_code == 0
    Ext.assert_called_once_with(debug_dir="data/debug")


def test_assistant_no_subcommand_prints_hint(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["assistant"])
    assert "psc assistant start" in result.output


# ---- erase-all ----


def test_erase_all_aborts_when_user_declines(runner: CliRunner) -> None:
    fake_session = MagicMock()
    fake_session.run.return_value.single.return_value = {"c": 5}

    from contextlib import contextmanager

    @contextmanager
    def _fake_neo_session():
        yield fake_session

    fake_conn = MagicMock()
    fake_conn.execute.return_value.fetchone.return_value = {"c": 3}

    @contextmanager
    def _fake_get_conn():
        yield fake_conn

    with (
        patch("pearscarf.storage.db.init_db"),
        patch("pearscarf.storage.neo4j_client.get_session", _fake_neo_session),
        patch("pearscarf.storage.db._get_conn", _fake_get_conn),
        patch(
            "pearscarf.storage.vectorstore._get_client",
            return_value=MagicMock(
                get_collection=MagicMock(return_value=MagicMock(points_count=2))
            ),
        ),
        patch("pearscarf.storage.neo4j_client.close"),
    ):
        result = runner.invoke(cli, ["erase-all"], input="n\n")
    assert "Aborted" in result.output


def test_erase_all_short_circuits_when_empty(runner: CliRunner) -> None:
    fake_session = MagicMock()
    fake_session.run.return_value.single.return_value = {"c": 0}

    from contextlib import contextmanager

    @contextmanager
    def _fake_neo_session():
        yield fake_session

    fake_conn = MagicMock()
    fake_conn.execute.return_value.fetchone.return_value = {"c": 0}

    @contextmanager
    def _fake_get_conn():
        yield fake_conn

    fake_qdrant = MagicMock()
    fake_qdrant.get_collection.return_value.points_count = 0

    with (
        patch("pearscarf.storage.db.init_db"),
        patch("pearscarf.storage.neo4j_client.get_session", _fake_neo_session),
        patch("pearscarf.storage.db._get_conn", _fake_get_conn),
        patch("pearscarf.storage.vectorstore._get_client", return_value=fake_qdrant),
    ):
        result = runner.invoke(cli, ["erase-all"])
    assert "Nothing to do" in result.output
