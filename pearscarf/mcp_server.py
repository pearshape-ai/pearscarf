"""MCP server — exposes PearScarf context queries via FastMCP over HTTP/SSE.

Tools are registered in 1.15.2–1.15.5. This module provides the server
bootstrap, auth middleware, and health endpoint.
"""

from __future__ import annotations

import threading

from fastmcp import FastMCP

from pearscarf.config import MCP_HOST, MCP_PORT
from pearscarf.db import init_db


mcp = FastMCP("PearScarf")


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    """Health check — no auth required."""
    from starlette.responses import JSONResponse
    from pearscarf import __version__
    return JSONResponse({"status": "ok", "version": __version__})


class MCPServer:
    """Background thread running the FastMCP server."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        init_db()
        mcp.run(
            transport="sse",
            host=MCP_HOST,
            port=MCP_PORT,
        )

    def start(self) -> None:
        """Start MCP server in a background daemon thread."""
        self._thread = threading.Thread(
            target=self._run, name="mcp-server", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        # FastMCP doesn't expose a clean shutdown — daemon thread dies with process
        pass

    def run_foreground(self) -> None:
        """Run MCP server in the foreground (blocking)."""
        init_db()
        print(f"MCP server starting on {MCP_HOST}:{MCP_PORT}")
        mcp.run(
            transport="sse",
            host=MCP_HOST,
            port=MCP_PORT,
        )
