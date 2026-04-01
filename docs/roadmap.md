# Roadmap

PearScarf is a self-improving, reality-aligned context engine for teams of agents. Together, these agents become the operational backbone for companies.

## Temporal Entity Graph

The graph is the connective tissue of the system. Every piece of data — emails, issues, knowledge — gets decomposed into entities and facts that evolve over time. Entities are nodes. Facts are labeled, directed edges between them, carrying temporal metadata and full source provenance.

- ~~**Facts as edges** — entities and Day nodes are the only node types. Facts are categorized edges with temporal metadata and source references~~ (done — v1.8.x)
- **Entity extraction** — runs on every incoming record, extracts entities and categorized facts with confidence scores, driven by an editable prompt. Three edge labels cover the operational world: organizational attachments, claims and assertions, and observed state transitions. Every fact carries event time, transaction time, confidence, and a direct link back to the source record.
- **Entity resolution** — the hardest problem. Matching different surface forms of the same real-world entity to one node. Alias accumulation, confidence scoring, human-in-the-loop confirmation when uncertain. Entities get richer over time as more records reference them.
- **Verification & Augmentation Agent** — a separate async agent that runs outside the write path. Resolves ambiguous facts where two conflicting claims exist with equal recency. Moves inferred facts toward verified by seeking corroborating sources. Enriches entity records with missing data from external sources. Flags irresolvable cases for human review. This is the self-improvement loop — the write path is fast and non-blocking, reality-alignment deepens over time.
- **Ontology agent** — handles uncertain entity types and fact categories via human-in-the-loop, updates the extraction prompt from human feedback, runs evals to verify improvements don't regress quality. The system learns what matters in your world and gets better at extracting it.
- **Safety controls** — staging before graph commits, human-in-the-loop early on, nightly backups.

## Structured Data Store

The graph captures relationships and narrative. The structured store captures the current state of things that need to be precise and queryable — numbers, statuses, pipeline stages, financial transactions. Both are fed from the same extraction step, so they stay in sync without separate pipelines.

- **Current-state tables** — maintain precise, queryable business data alongside the temporal graph. Same extraction feeds both.
- **Domain tables** — company metrics, pipeline, customer profiles, contacts — human-defined schemas, agent-populated.
- **Event sourcing** — EXPLORE appending state changes as events so structured data also has temporal history.

## Extraction Quality & Eval

Everything depends on extraction quality. The extraction prompt, fact categories, entity normalization, and automated record handling all need to be proven against real data with structured evaluation — not eyeballing. See [Eval Metrics](eval-metrics.md) for the metric definitions, tiers, and ground truth schema.

- **Synthetic test corpus** — generated emails and issues covering edge cases: multi-party threads, entity name variations, contradicting facts, cross-source references, automated notifications. Separate repo with generation scripts.
- **Ground truth annotations** — expected entities and facts for each test record, manually verified.
- ~~**Eval harness** — run extraction against the corpus, diff against expected output, score per entity type and per fact category. Precision, recall, entity resolution accuracy.~~ (done — v1.10.0)
- **Regression testing** — every prompt change runs the full eval. No change ships if scores drop.

## Linear Integration

Second data source to prove the system works beyond email. Issues flow through the same extraction pipeline, producing entities that connect to email-derived entities through the graph.

- ~~**Linear expert agent** — second data source via direct API, validates the architecture works across heterogeneous data~~ (done — v1.6.x)
- ~~**Shared pipeline** — issues feed through the same extraction → graph + vector store~~ (done — v1.6.2)
- **Cross-source entity resolution** — an email mentioning "Acme integration" connects to a Linear issue about "Acme API Integration" through the same graph entity. Depends on entity resolution work above.

## Framework & Plugin Architecture

PearScarf becomes a framework where expert agents are self-contained plugins. Each plugin brings its own connection, schema, extraction semantics, polling logic, and tools. PearScarf core handles the graph, extraction pipeline, retriever, entity resolution, and Day nodes. Adding a new data source means writing a plugin, not forking the project.

- **Plugin interface** — define the contract an expert agent must implement: connection config, record schema, content builder, polling logic, tools.
- **Expert agent packages** — Gmail and Linear become the reference implementations of the plugin interface.
- **Plugin discovery and registration** — drop a plugin in, PearScarf picks it up, starts polling, feeds extraction.
- **Agents generating agents** — an agent can create a new expert agent plugin from a data source description. The system expands its own capabilities.

## Agentic Framework Integrations

PearScarf is the context layer underneath any agent framework. Agents from any framework query PearScarf for context instead of connecting to raw data sources individually.

- **MCP server** — PearScarf exposes a read-only query surface via MCP. Two layers: a primitive layer for direct, composable graph queries, and a convenience layer for the most common multi-call patterns collapsed into one. Any MCP-compatible agent can consume it.
- **OpenClaw integration** — PearScarf as shared memory for OpenClaw agents. External systems are the shared bus — PearScarf observes, OpenClaw acts.
- **LangGraph / other frameworks** — PearScarf as a tool provider. Same MCP interface, different consumers.

## Trust & Human Control

This is not a separate phase of work — it's a design principle that runs through everything. Every feature is built with the assumption that humans need full visibility and control before they'll trust an autonomous system with their data.

**The goal: humans have 100% control, so they develop at least 80% trust.**

Trust is earned through:

- **Provenance** — every fact traces back to its source record. You can always answer "where did this come from" and "why does the system believe this." Facts are extracted close to the source text — never summarised, never paraphrased — to keep hallucination surface small.
- **Temporal transparency** — nothing is silently overwritten. Facts are staled and pointed to their replacement, not deleted. The full history of what the system believed and when is preserved and queryable.
- **Confidence surfacing** — four confidence levels: inferred from context, explicitly stated in a record, verified by an authoritative source, retracted as incorrect. Consumers know what to trust and why.
- **Observability** — every LLM call, every graph write, every query is traced. The system shows its work.
- **Human-in-the-loop at every uncertain boundary** — triage (is this record relevant?), entity resolution (are these the same person?), graph correction (that fact is wrong), ontology updates (start tracking this new entity type). The system asks when it's not confident.
- **Graph correction loop** — humans can tell the system "that's wrong" through natural language. The worker invalidates the edge, records the correction, and the verification agent learns from it.
- **Audit log** — a queryable log of every graph mutation. What changed, when, triggered by what record, confirmed by human or auto-applied.
- **Regression-tested extraction** — prompt changes are evaluated against a ground truth corpus before shipping. The system doesn't silently get worse.

If people can't understand why the system "believes" what it "believes", they won't use it or let their agents use it. If they can't correct it when it's wrong, they won't trust it. PearScarf is built from the ground up with the conviction that transparency and human control are not features — they're prerequisites.