# Connecting an MCP client to PearScarf

PearScarf's MCP surface is consumable by any MCP-compatible agent — Claude Code, Claude Desktop, or a custom client. This doc covers the common setups. See [mcp_tools.md](mcp_tools.md) for the tool reference.

## Prerequisites

- PearScarf running, with the MCP server reachable at an HTTP/SSE URL. Two common shapes:
  - **Local**: `http://localhost:8090/sse` (via `psc mcp start` or the bundled monolith path).
  - **Remote**: an HTTPS URL you expose yourself (e.g. behind a Cloudflare Tunnel, reverse proxy, or cloud LB). PearScarf doesn't prescribe a host — you pick.
- An API key. Create one with the pearscarf CLI (from wherever `psc` is installed — your laptop, the container, etc.):

```bash
psc mcp keys create --name "my-client"
# Key: psk_...
# Save this — it's not retrievable later.
```

Name each key after the client that uses it. Revoke per-client with `psc mcp keys revoke <key_id>`.

## Claude Code

### CLI

```bash
claude mcp add \
  --transport sse \
  pearscarf \
  https://your-pearscarf-host/sse \
  --header "Authorization: Bearer psk_..."
```

Flag names have evolved across Claude Code versions; `claude mcp --help` prints the current options.

### JSON config

Alternatively, edit Claude Code's config file (location varies — run `claude mcp list` to find it) and add:

```json
{
  "mcpServers": {
    "pearscarf": {
      "type": "sse",
      "url": "https://your-pearscarf-host/sse",
      "headers": {
        "Authorization": "Bearer psk_..."
      }
    }
  }
}
```

Restart Claude Code (or reload the session with `claude -c`) for the server to be picked up.

## Claude Desktop

Edit the Claude Desktop config:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Add the same `mcpServers` block shown above. Restart Claude Desktop.

## Generic SSE client

Any HTTP client that speaks MCP-over-SSE works:

- **Endpoint**: `GET <base-url>/sse` with `Accept: text/event-stream`
- **Auth**: `Authorization: Bearer psk_...` header on every request
- **Protocol**: standard MCP 1.0 SSE transport — tool discovery via `tools/list`, invocation via `tools/call`

## Verification

From the client, list tools. You should see ten: `find_entity`, `get_facts`, `get_connections`, `get_relationship`, `get_conflicts`, `get_current_state`, `get_entity_context`, `get_open_blockers`, `get_open_commitments`, `get_recent_activity`.

Quick functional probe:

```
find_entity(name="some known entity")
```

Returns a list with matching entities (can be empty if the name isn't known). No errors means auth + transport + tool routing are all working.

## Rotation

Tokens don't auto-expire. Rotate by minting a new one, updating the client config, then revoking the old:

```bash
psc mcp keys create --name "my-client-v2"
# update client config to new token, restart client
psc mcp keys revoke <old-key-id>
```

If a key leaks, revoke immediately — revoked keys stop authenticating on the next request.

## Troubleshooting

- **401 / 403 on any tool call** — token is wrong, expired, or revoked. Mint fresh via `psc mcp keys create`.
- **Connection hangs or SSE stream drops** — network path to the PearScarf host; check your proxy / tunnel config.
- **Tool list empty after `mcp add`** — client didn't reload; restart it.
- **`find_entity` returns empty for everything** — graph isn't populated yet. Run an ingestion (`psc expert start-ingestion <name>`) or seed (`psc expert ingest --seed <file>`).
