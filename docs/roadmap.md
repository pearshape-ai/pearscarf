# Roadmap

## Now: Memory Backend Evaluation

Mem0 is integrated as the first pluggable memory backend behind the Retriever, with Neo4j as the graph store. The SQLite pipeline remains as a fallback.

Next: integrate Graphiti and Cognee as alternative backends behind the same interface. Test all three against real email data. Let usage decide which one wins.

## TODO

- Linear expert agent via MCP — second data source, validate cross-source entity connection
- Cloud deployment — always-on system running on Mac Mini or cloud, Gmail polling, Discord as the human interface
- Implicit retrieval — worker auto-retrieves context before responding, without the human asking
- Observability — LangSmith or Langfuse for trace visualization, cost tracking, and evaluation
- Additional expert agents (Calendar, CRM) as the pattern stabilizes
