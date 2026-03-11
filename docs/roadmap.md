# Roadmap

## Now: Storage & Context

The agent communication layer works. Triage works. The pipeline works. What needs to get right is the quality of stored context — how well heterogeneous operational data gets connected, stored, and surfaced to models when they need it.

Evaluating memory backends (Mem0, Graphiti, Cognee) as a pluggable storage layer behind the Retriever. Goal: integrate all three with an on/off switch, test against real email data, and let usage decide which one wins.

## TODO

- Linear expert agent via MCP — second data source, validate cross-source entity connection
- Cloud deployment — always-on system running on Mac Mini or cloud, Gmail polling, Discord as the human interface
- Implicit retrieval — worker auto-retrieves context before responding, without the human asking
- Observability — LangSmith or Langfuse for trace visualization, cost tracking, and evaluation
- Additional expert agents (Calendar, CRM) as the pattern stabilizes
