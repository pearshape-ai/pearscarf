"""FastMCP AuthProvider that verifies incoming `Authorization: Bearer <key>`
headers against pearscarf's `mcp_keys` Postgres table.

When this provider is installed on the FastMCP server, every MCP-routed
request must carry a Bearer token that matches a non-revoked row in
`mcp_keys`. Mismatched or missing tokens are rejected (401) before any
tool runs. Successful verifications update the key's `last_used_at`.

Bootstrap order (operator responsibility, not enforced in code):
1. `psc mcp-keys create <device>` to issue at least one key.
2. Restart the MCP server (or deploy a new image that installs this
   provider). Any client that wants to call MCP tools must send the
   raw key as `Authorization: Bearer <key>`.

`@mcp.custom_route` endpoints (e.g. `/health`) bypass this middleware —
FastMCP only wires auth into the MCP transport routes (`/mcp`, `/sse`).
"""

from __future__ import annotations

from fastmcp.server.auth.auth import AccessToken, AuthProvider

from pearscarf.storage.store import verify_mcp_key


class PearscarfAuthProvider(AuthProvider):
    """Bearer-token auth against the `mcp_keys` table."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token:
            return None
        row = verify_mcp_key(token)
        if row is None:
            return None
        # client_id is the key's human-readable name — surfaces in audit /
        # logging downstream.
        return AccessToken(token=token, client_id=row["name"], scopes=[])
