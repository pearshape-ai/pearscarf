"""Linear background ingestion loop.

Polls Linear for new issues and changes, saves each as a record via
ctx.storage.save_record(), and notifies the worker via the bus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pearscarf.expert_context import ExpertContext


def start(ctx: ExpertContext) -> None:
    """Start the Linear ingestion loop as a daemon thread.

    Stub — implemented in PEA-88.
    """
    return None
