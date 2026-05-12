"""Root pytest config for pearscarf.

Adds a `--integration` CLI flag. By default, integration tests are skipped
so a bare `pytest` run stays fast and doesn't require a live database
stack. Pass `--integration` to opt in:

    pytest --integration          # runs only after `scripts/test-stack.sh up`
    pytest tests/integration/     # also works; selects the dir directly,
                                  # but integration-marked tests inside it
                                  # still skip without --integration

CI runs `pytest tests/unit/` explicitly, so this flag never matters there.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help=(
            "Run integration tests against the isolated test stack. "
            "Requires `scripts/test-stack.sh up` first."
        ),
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--integration"):
        return
    skip_marker = pytest.mark.skip(reason="needs --integration (test stack required)")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)
