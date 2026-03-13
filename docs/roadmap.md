# Roadmap

## Now: Graph Backend Evaluation

Mem0 has been removed — extraction quality and visibility were insufficient for operational data. The Postgres facts + graph + Qdrant pipeline is the active storage backend. All application data lives in Postgres (docker-compose); ChromaDB replaced by Qdrant; SQLite fully removed.

Next: evaluate Graphiti and Cognee as alternative graph backends with direct Neo4j integration. Neo4j and Qdrant Docker configs are retained and ready.

## TODO

- Linear expert agent via MCP — second data source, validate cross-source entity connection
- Cloud deployment — always-on system running on Mac Mini or cloud, Gmail polling, Discord as the human interface
- Implicit retrieval — worker auto-retrieves context before responding, without the human asking
- ~~Observability~~ — done (LangSmith, v1.1.0)
- Additional expert agents (Calendar, CRM) as the pattern stabilizes
