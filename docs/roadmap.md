# Roadmap

Build a self-improving context engine for a team of agents.
Together, these agents become the operational backbone for companies.

## Temporal Entity Graph

The graph is the connective tissue of the system. Every piece of data — emails, issues, knowledge — gets decomposed into entities and relationships that evolve over time. The extraction agent does the work, the ontology agent ensures the system learns what to look for, and the safety controls prevent runaway writes.

- **Fact-as-an-edge** — adopt bi-temporal timestamps on all entity relationships to track how facts evolve over time
- **Entity extraction agent** — runs on every incoming record, extracts entities and relationships with confidence scores, driven by an editable ontology prompt
- **Ontology agent** — handles uncertain entities via HIL, updates the extraction prompt from human feedback, runs evals to verify improvements
- **Safety controls** — staging before graph commits, heavy HIL early on, nightly backups

## Structured Data Store

The graph captures relationships and history. The structured store captures the current state of things that need to be precise and queryable — numbers, statuses, pipeline stages. Both are fed from the same extraction step, so they stay in sync without separate pipelines.

- **Postgres current-state tables** — maintain precise, queryable business data alongside the temporal graph, same extraction feeds both
- **Domain tables** — company metrics, pipeline, customer profiles, contacts — human-defined schemas, agent-populated
- **Event sourcing** — EXPLORE appending state changes as events so structured data also has temporal history

## Linear Integration

Second data source to prove the system works beyond email. Issues flow through the same extraction pipeline, producing entities that connect to email-derived entities through the graph. An email about "Acme integration" and a Linear issue titled "Acme API integration" should resolve to the same entity without explicit wiring.

- **Linear expert agent** — second data source via MCP, validates the architecture works across heterogeneous data
- **Shared pipeline** — issues feed through the same extraction → graph + structured store
- **Cross-source entity resolution** — an email mentioning "Acme integration" connects to a Linear issue about "Acme API integration" through the same graph entity

## Entity Recognition Eval

Everything depends on extraction quality. Before building the graph, the structured store, or the Linear integration, the extraction prompt needs to be proven against real data. The eval set is the ground truth the system measures itself against, and the prompt iteration is how it gets good enough to trust.

- **Annotated test set** — 30-50 real emails with manually labeled entities and relationships
- **Eval script** — run extraction prompt against test set, compare to annotations, score accuracy
