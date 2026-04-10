"""Gmail background ingestion loop.

Polls Gmail for new emails, saves each as a record via
ctx.storage.save_record(), and notifies the worker via the bus.

Stub — real implementation in a follow-up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pearscarf.expert_context import ExpertContext


def start(ctx: ExpertContext) -> None:
    """Start the Gmail ingestion loop as a daemon thread.

    Does nothing in this stub. The real implementation will create a
    GmailConnect instance, poll for unread emails, and save them via
    ctx.storage.save_record().
    """
    ctx.log.write(ctx.expert_name, "action", "gmail_ingest stub — not polling")
