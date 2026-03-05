# Vision

## Core Architecture

The core architectural principle is separation of concerns: experts own their domains, the worker reasons, the storage layer connects everything.

How an expert accesses its domain — headless browser, MCP, raw API, whatever — is an implementation detail. The system doesn't care. Pick the right tool for the job. The architecture supports swapping between transport mechanisms without touching anything outside the expert.

The real differentiator is the context layer: how well heterogeneous data gets connected, stored, and surfaced to models when they need it. MCPs, APIs, and headless browsers are all valid transport mechanisms. What matters is what happens after the data arrives.

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

Each expert agent owns a domain and accesses it through whatever transport makes sense — MCP, API, or headless browser:

    Worker
      +-- Gmail Expert (email — MCP with OAuth)
      +-- Linear Expert (issues, project tracking — MCP)
      +-- Calendar Expert (events, scheduling)
      +-- CRM Expert (contacts, deals)
      +-- ... any tool with an API, MCP, or accessible UI

Each expert writes to its own typed tables. The knowledge graph connects them through shared entities. An email mentioning an issue links to the Linear issue automatically — no explicit integration between the two experts needed.

## Always-On Deployment

The target state: PearScaff running on a Mac Mini or cloud instance. Gmail expert polling for new emails. Worker triaging and responding. Indexer building context in the background. Discord as the human interface. Always listening, always learning.
