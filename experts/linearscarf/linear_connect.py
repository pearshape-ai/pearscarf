"""Linear API client + tool definitions.

Provides LinearConnect (GraphQL client, tools, ingest_record) and the
module-level get_tools(ctx) entry point called by pearscarf at startup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pearscarf.expert_context import ExpertContext


class LinearConnect:
    """Authenticated Linear client + tool factory.

    Shared by both the LLM agent (via get_tools) and the ingester
    (via ingest_record). One API client, no duplication.
    """

    def __init__(self, ctx: ExpertContext) -> None:
        self._ctx = ctx

    def ingest_record(self, data: dict) -> str | None:
        """Save a record from a JSON fixture or API response.

        Returns record_id or None on duplicate.
        """
        # Stub — implemented in PEA-88
        return None

    def get_tools(self) -> list:
        """Return the list of BaseTool instances for the LLM agent."""
        # Stub — implemented in PEA-88
        return []


def get_tools(ctx: ExpertContext) -> LinearConnect:
    """Entry point called by pearscarf at startup."""
    return LinearConnect(ctx)
