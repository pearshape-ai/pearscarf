# Usage

## Commands

| Command | Description |
|---|---|
| `psc run` | Worker + experts + indexer + MCP server + session REPL |
| `psc run --poll` | Full system + expert ingesters (background polling) |
| `psc discord` | Full system with Discord frontend |
| `psc discord --poll` | Discord + expert ingesters |
| `psc chat` | Direct chat (no session bus) |
| `psc install <path>` | Install an expert package |
| `psc update <name>` | Update an installed expert to new version |
| `psc expert list` | List installed experts |
| `psc expert inspect <name>` | Show expert details |
| `psc expert disable <name>` | Disable an expert (reversible) |
| `psc expert enable <name>` | Re-enable a disabled expert |
| `psc expert uninstall <name>` | Uninstall an expert |
| `psc expert gmail --auth` | Gmail OAuth setup |
| `psc expert ingest` | Standalone ingest expert (interactive mode) |
| `psc expert ingest --seed <file>` | Ingest a seed file |
| `psc expert ingest --record <file> --type <type>` | Ingest typed JSON records |
| `psc eval --dataset <path>` | Graph-based eval: ingest, index, query graph, score |
| `psc eval --dataset <path> -v` | Verbose eval with per-record detail |
| `psc erase-all` | Wipe all system state |
| `psc queue` | Curator queue summary |
| `psc queue list` | List up to 20 queue entries |
| `psc queue clear --confirm` | Clear unclaimed queue entries |
| `psc indexer start` | Start the indexer in the foreground |
| `psc curator start` | Start the curator in the foreground |
| `psc curator status` | Show curator queue status |
| `psc mcp start` | Run MCP server standalone |
| `psc mcp status` | Show MCP server info |
| `psc mcp keys list` | List all API keys |
| `psc mcp keys create --name <n>` | Create a new API key |
| `psc mcp keys revoke <key_id>` | Revoke an API key |
| `psc query <tool> [--options]` | Call a context_query tool directly |
| `psc integration-test` | Smoke test all context_query tools |

All commands also available as `pearscarf` instead of `psc`.

### `psc query` tool names

Valid tools: `find_entity`, `get_facts`, `get_connections`, `get_relationship`, `get_conflicts`, `vector_search`.

Examples:
```bash
psc query find_entity --name "Marcus Webb"
psc query get_facts --entity-name "Marcus Webb" --edge-label AFFILIATED
psc query get_connections --entity-name "Meridian Deal"
psc query get_relationship --entity-a "Marcus Webb" --entity-b "Meridian Deal"
psc query get_conflicts --entity-name "James Whitfield"
psc query vector_search --name "contract markup"
```

## Session REPL (`psc run`)

The REPL shows the active session in the prompt:

```
[ses_001] you > Read my latest emails
```

### REPL Commands

| Command | Description |
|---|---|
| `/sessions` | List all sessions |
| `/switch <id>` | Switch to a different session |
| `/new` | Create a new session |
| `/history` | Print messages in current session |
| `/history <id>` | Print messages in a specific session |

### Message Flow

1. Your message → **worker agent** via Postgres
2. Worker reasons → may delegate to an **expert** (gmailscarf, linearscarf, githubscarf)
3. Expert processes the request using its tools
4. Result flows back: expert → worker → you

### Notifications

Expert-initiated sessions (e.g. new email detected during polling):
```
--- NEW MESSAGE ses_003: worker — New email from investor@acme.com ---
```

Use `/switch ses_003` to interact.

## Discord (`psc discord`)

- Mention the bot or DM → new session + thread
- Thread replies stay in the same session
- Expert events auto-create threads
- Sessions persist — resume by posting in the thread

## Memory Inspection

| Command | Description |
|---|---|
| `psc memory list` | List recent records from Qdrant |
| `psc memory search "query"` | Semantic search across records |
| `psc memory entity "name"` | Look up entity + connections + fact history |
| `psc memory graph` | Graph overview and stats |
| `psc memory record <id>` | Entities and facts extracted from a record |

Same commands available in the REPL via `/memory`.

## Scripts

| Script | Description |
|---|---|
| `python scripts/reindex_all.py` | Reset indexed flags — indexer re-extracts on next poll |
| `python scripts/erase_all.py` | Wipe all system state |
| `python scripts/extract_test.py [ids...]` | Run extraction prompt against records (no writes) |

## See also

- [Getting Started](getting-started.md) — installation, credentials, first run
- [Architecture](architecture.md) — system design, expert contract
- [Building an Expert](expert_guide.md) — how to create a new expert
- [MCP Tools](mcp_tools.md) — external tool surface reference
