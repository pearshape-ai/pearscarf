"""Integration tests for MCP dual-transport support (SSE + HTTP)."""

from __future__ import annotations

import asyncio
import time

import pytest

# These tests require the test stack to be running (scripts/test-stack.sh up)
pytestmark = pytest.mark.integration


async def _call_get_schema_sse() -> dict:
    """Call get_schema via SSE transport."""
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async with sse_client("http://localhost:8090/sse") as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            result = await session.call_tool("get_schema", {})
            return result.content[0].text if result.content else {}


async def _call_get_schema_http() -> dict:
    """Call get_schema via streamable HTTP transport."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client("http://localhost:8091/mcp") as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            result = await session.call_tool("get_schema", {})
            return result.content[0].text if result.content else {}


def test_dual_transport_get_schema_identical() -> None:
    """Both SSE and HTTP transports return identical get_schema output."""
    import json

    # Give the MCP server a moment to be ready
    time.sleep(1)

    sse_result = asyncio.run(asyncio.wait_for(_call_get_schema_sse(), timeout=10))
    http_result = asyncio.run(asyncio.wait_for(_call_get_schema_http(), timeout=10))

    # Parse the JSON text responses
    sse_schema = json.loads(sse_result)
    http_schema = json.loads(http_result)

    # Both should have the same keys
    assert set(sse_schema.keys()) == set(http_schema.keys())
    assert "entity_types" in sse_schema
    assert "edge_labels" in sse_schema
    assert "fact_types" in sse_schema
    assert "source_types" in sse_schema

    # Content should match
    assert sse_schema["entity_types"] == http_schema["entity_types"]
    assert sse_schema["edge_labels"] == http_schema["edge_labels"]
    assert sse_schema["fact_types"] == http_schema["fact_types"]
