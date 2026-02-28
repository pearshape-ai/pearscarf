from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pearscaff.agents.base import BaseAgent
from pearscaff.tools import ToolRegistry


class WorkerAgent(BaseAgent):
    def __init__(
        self,
        tool_registry: ToolRegistry,
        on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        super().__init__(tool_registry=tool_registry, on_tool_call=on_tool_call)
