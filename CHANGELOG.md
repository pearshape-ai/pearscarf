# Changelog

## 1.2.0
- Removed Mem0 integration — extraction quality and visibility insufficient for operational data
- Restored SQLite facts + graph + ChromaDB as the sole storage pipeline
- Removed MemoryBackend abstraction — indexer and retriever use graph.py/vectorstore.py directly
- Removed mem0ai dependency (and transitive qdrant-client, openai, etc.)
- Removed MEMORY_BACKEND, OPENAI_API_KEY, OPENAI_MODEL, QDRANT_URL config
- Neo4j and Qdrant Docker configs retained for future Graphiti/Cognee evaluation
- Memory inspection CLI and REPL commands updated to use SQLite directly

## 1.1.3
- Mem0 LLM provider switched from Anthropic to OpenAI (Mem0's native provider)
- Removed Anthropic compatibility patches (top_p, tool_choice, tool format)
- Added OPENAI_API_KEY and OPENAI_MODEL config (default: gpt-4o-mini)
- Qdrant switched from local file-based to server (Docker) — fixes multi-process locking
- All data consolidated under `data/` directory (SQLite, ChromaDB, logs, Neo4j, Qdrant, browser state)
- Fixed Qdrant exit traceback (neutered `__del__`, explicit atexit cleanup)

## 1.1.2
- Memory inspection CLI: `ps memory list/search/entity/graph/record`
- `ps memory list -f` — tail-style real-time memory watching
- Same commands in REPL via `/memory`
- Direct Neo4j graph queries for entity lookup and stats (Mem0 backend)
- SQLite backend: entity lookup, graph stats, record-level memory tracing
- Read-only — no memory editing or deletion

## 1.1.0
- LangSmith integration for observability (opt-in)
- Hierarchical tracing: agent runs, LLM calls, tool executions, memory operations
- Traces tagged with agent name, session ID, record ID
- Cost and token tracking across all agents including Mem0
- session.log preserved as local fallback

## 1.0.0
- Mem0 integration as pluggable memory backend (Neo4j graph + vector)
- Custom extraction prompt for operational email data
- Indexer simplified: delegates extraction to memory backend
- Retriever unified: single memory_search replaces facts/graph/vector queries when using Mem0
- MEMORY_BACKEND env var for switching between mem0 and sqlite
- SQLite pipeline preserved as fallback (default)

## 0.11.1
- Roadmap restructured to high-level prose milestones
- Changelog created (this file) — factual record of completed work
- Completed-item checkboxes moved out of roadmap into changelog

## 0.11.0
- Gmail expert MCP integration (OAuth, API-based email operations)
- Email polling loop with --poll-email flag (configurable interval)
- New email notifications on Discord and REPL
- MCP as default transport when configured, headless browser as fallback
- pearscaff gmail --auth command for OAuth setup

## 0.10.0
- Roadmap and vision docs update
- Balanced vision framing (transport-agnostic expert architecture)

## 0.9.1
- Project documentation: architecture diagrams, vision, roadmap, getting-started

## 0.9.0
- Retriever agent (explicit context queries)
- Three query modes: facts lookup, graph traversal, vector search
- Structured context packages returned to worker

## 0.8.0
- HIL triage (auto-classify or ask human)
- Human context capture during triage (fed to Indexer)
- Classification override support
- All classification activity visible on Discord and REPL

## 0.7.0
- ChromaDB integration (vector embeddings with sentence-transformers)
- Indexer embeds record content for semantic search

## 0.6.0
- Knowledge graph (entities, edges, facts, entity_types registry)
- Indexer agent (background LLM extraction into graph)

## 0.5.0
- System of Record (expert-owned storage, email deduplication)

## 0.4.0
- Unified session logging (actions, tool calls, reasoning, thinking, errors)
- Versioning (ps --version)
- REPL UX improvements

## 0.3.0
- Session-based async communication via SQLite
- Terminal REPL with session management
- Discord bot with thread-per-session mapping

## 0.2.0
- Worker agent with reasoning and task routing

## 0.1.0
- Gmail expert agent (headless browser, reads emails, marks as read)
