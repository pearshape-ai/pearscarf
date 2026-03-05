# Roadmap

## Completed

- [x] v0.1.0 — Gmail expert agent (headless browser, reads emails, marks as read)
- [x] v0.2.0 — Worker agent with reasoning and task routing
- [x] v0.3.0 — Session-based async communication via SQLite
- [x] v0.3.0 — Terminal REPL with session management (/sessions, /switch, /new, /history)
- [x] v0.3.0 — Discord bot with thread-per-session mapping
- [x] v0.4.0 — Unified session logging (actions, tool calls, reasoning, thinking, errors)
- [x] v0.4.5 — Versioning (ps --version), REPL UX improvements
- [x] v0.5.0 — System of Record (expert-owned storage, email deduplication)
- [x] v0.6.0 — Knowledge graph (entities, edges, facts, entity_types registry)
- [x] v0.6.0 — Indexer agent (background LLM extraction into graph)
- [x] v0.7.0 — ChromaDB integration (vector embeddings with sentence-transformers)
- [x] v0.8.0 — HIL triage (auto-classify or ask human, Discord + REPL visibility)
- [x] v0.8.0 — Human context capture (responses stored, fed to Indexer)
- [x] v0.8.0 — Classification override support
- [x] v0.9.0 — Retriever agent (explicit context queries: facts, graph, vector)
- [x] v0.9.1 — Project documentation (vision, roadmap, diagrams)
- [x] v0.9.2 — Gmail session expiry detection (immediate error instead of silent failure)
- [x] v0.9.3 — Discord bot fixes (role mention support, on_message error handling)
- [x] v0.10.0 — Roadmap and vision evolution (docs only)

## Next

- [ ] v0.11.0 — Mem0 integration (replace facts table + ChromaDB with Mem0 memory layer)
- [ ] v0.12.0 — Gmail MCP (OAuth, email polling loop, notifications)
- [ ] v0.13.0 — Context quality (LLM-assisted entity resolution, memory quality filtering, re-indexing)
- [ ] v0.14.0 — LangSmith integration (traces, cost tracking)
- [ ] v0.15.0 — Linear expert via MCP (second data source, cross-source context)

## Backlog

- [ ] Implicit retrieval (worker auto-retrieves context on incoming events)
- [ ] Cloud deployment (Mac Mini or cloud, always on)
- [ ] Batch email loading (load historical emails, bulk classify)
- [ ] Dynamic entity type discovery (Indexer suggests new types)
- [ ] Retriever caching (avoid redundant lookups)
- [ ] Retriever relevance scoring (rank results)
- [ ] Cross-query memory (Retriever remembers what was asked before)
- [ ] REPL commands for browsing records, graph, memories
- [ ] Worker confidence scoring on auto-classifications
- [ ] Self-improving extraction prompts (Indexer learns from corrections)
- [ ] Multi-user support

## Exploratory

- [ ] Third+ expert agents (Calendar, CRM, etc.)
- [ ] Headless browser expert for tools without APIs/MCPs
- [ ] Network interception pattern (capture app API calls via CDP)
- [ ] Agent-to-agent protocol formalization (A2A inspiration)
