# Vision

## Thesis

MCPs are a transitional technology. Pre-built connectors work today but they're rigid — every new integration requires a new connector, every API change breaks things.

The future is expert agents that navigate UIs directly via headless browsers, coordinated by a context-savvy worker agent. The API contract between agents is natural language intent, not schema. Agent-to-agent communication replaces API-to-API integration.

PearScaff is built to prove this thesis.

## How the System Learns

The system gets smarter through use, not through training:

1. **HIL triage teaches classification.** When you tell the worker "this email is relevant because Michael is a partner," the system stores that context. Next time Michael emails, auto-classified.

2. **The graph grows with every record.** New entities, relationships, and facts are extracted from every relevant email. The more data flows through, the richer the context.

3. **Auto-classification improves as entities accumulate.** Week one: the worker asks you about 80% of emails. Month one: 20%. The known-entity check catches most senders before the LLM needs to classify.

4. **Human context enriches extraction.** Your responses during triage are passed to the Indexer alongside the email. The LLM extracts better entities because it has your annotation.

## Retrieval: Explicit and Implicit

### Explicit (v0.9.0)
You ask the worker a question. The worker calls the Retriever. The Retriever queries facts, walks the graph, searches vectors, and returns a context package.

Examples:
- "What do I know about Acme Corp?"
- "Brief me on Michael Chen"
- "Any emails about fundraising?"

### Implicit (future)
The worker automatically retrieves context when processing incoming events — before you even ask.

A receipt arrives from Acme. Before responding, the worker asks the Retriever: what's the spend history? Any open issues? Who's the point of contact? You get a richer response without prompting it.

## Multi-Expert Future

Each expert agent owns a domain and operates its UI via headless browser:

    Worker
      +-- Gmail Expert (email)
      +-- Linear Expert (issues, project tracking)
      +-- Calendar Expert (events, scheduling)
      +-- CRM Expert (contacts, deals)
      +-- ... any UI accessible via browser

Each expert writes to its own typed tables. The knowledge graph connects them through shared entities. An email mentioning an issue links to the Linear issue automatically — no explicit integration between the two experts needed.

## Always-On Deployment

The target state: PearScaff running on a Mac Mini or cloud instance. Gmail expert polling for new emails. Worker triaging and responding. Indexer building context in the background. Discord as the human interface. Always listening, always learning.
