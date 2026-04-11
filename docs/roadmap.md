# PearScarf Roadmap

> For the engineering-oriented version of this roadmap, see [roadmap-eng.md](roadmap-eng.md). For the previous version of this roadmap, see [roadmap-v1.md](roadmap-v1.md).

## What it is

The people in a company hold the connections in their heads. Their agents don't.

PearScarf is a context engine for agent teams. It watches your operational data sources — email, issues, pull requests — extracts the entities and facts that matter, and maintains a shared knowledge graph that any agent can query. One call returns everything known about a person, deal, or project: what was said, who said it, when, and where. Two hundred tokens instead of ten thousand.

The endgame: a shared memory layer that improves itself. It starts by observing. Then it verifies. Then it learns what to look for. Humans stay in control throughout.

---

## What's done

**Knowledge graph** — PearScarf builds a structured record of your business world as it observes your tools. People, companies, projects, deals — and the facts connecting them: who works where, who committed to what, what changed, what was said. Every fact traces back to the source record it came from. Nothing is ever deleted; the full history of what the system knew and when is always preserved.

**Correct timelines** — PearScarf tracks both when something happened and when it learned about it. These can diverge — an email forwarded today about a January decision lands in January in the graph, not today. Records can arrive out of order and the timeline stays correct.

**Entity resolution** — "Michael", "M. Chen", "michael@acme.com", and "the VP of Engineering at Acme" all refer to the same person. PearScarf matches surface forms to known entities as records arrive, accumulating aliases over time. When the system isn't confident, it defers to a human rather than merging the wrong things.

**Source integrations** — PearScarf connects to your tools through expert agents — self-contained integrations that each own their connection, know what their data means, and can act on it. Three ship out of the box: Gmail, Linear, and GitHub. Adding a new source doesn't require changes to PearScarf core.

**Graph maintenance** — a background process keeps the graph semantically clean over time: equivalent facts that say the same thing get merged, commitments whose deadlines have passed get flagged, and facts gain confidence as more sources corroborate them. Structurally correct at write time; semantically clean as the curator runs.

**Agent query surface** — any MCP-compatible agent can connect to PearScarf and ask questions: who is this person, what's the current state of this deal, what commitments are outstanding, what's blocking this project. Structured answers, not raw records.

**Eval pipeline** — extraction quality is measured automatically against ground truth datasets. Every change can be tested before it ships. The system knows when it's getting better or worse, and regressions are visible across versions.

---

## In progress

**Entity resolution quality** — the hardest problem in the system. The same real-world entity gets referred to in many ways across many sources, and getting those references to reliably collapse to one node requires significant tuning work. One missed merge creates divergent fact trails that compound. This is the highest-leverage work right now.

---

## What's next

**Extraction quality** — the graph is only as good as what gets extracted. Iterating on prompts against a ground truth corpus, testing every change, tightening the feedback loop. Better extraction → better facts → better context → better agent decisions.

**Cross-source entity resolution** — the same entity gets named differently in email, issues, and pull requests. "Acme integration", "Acme API Integration", and "acme-api-client" should resolve to one node. Teaching the resolver to reason across sources, not just within them.

**Conversation continuity** — agents talking to PearScarf currently start a fresh conversation every time. Sessions should persist across turns so the context of what was already discussed carries forward.

**Real-time messaging** — the current internal message bus works but is too slow for production use. Replacing it is a prerequisite for reliable real-time behavior and for external agent connectivity.

---

## Horizon

**Verification and augmentation** — a separate agent that runs asynchronously and never blocks ingestion. It handles conflicts the write path can't resolve, seeks corroboration from external sources to upgrade uncertain facts toward confirmed, enriches entity records with missing data, and escalates genuinely irresolvable cases to a human. This is the self-improvement loop.

**Graph correction** — humans say "that's wrong" and the system acts on it: the fact is invalidated, the correction is recorded with provenance, and the pattern feeds back into future extraction. The graph learns from being wrong.

**Ontology learning** — today PearScarf extracts what matches its current understanding of the world. The ontology agent closes that loop: it learns what entity types and relationship categories matter for your specific deployment from human feedback, then updates extraction to match.

**Multi-agent backbone** — the longer arc is PearScarf as pure memory infrastructure: expert agents running anywhere, in any language, connecting via a standard protocol to share a single context layer. Records pushed in, context queried out. The architecture points here; the timing is post-MVP.

**Agents generating agents** — an agent that creates a new source integration from a description of the data source. The system expands its own coverage.

---

## Design principles

**Provenance** — every fact traces back to its source record. You can always answer "where did this come from."

**Temporal transparency** — nothing silently overwritten. The full history of what the system believed and when is always preserved and queryable.

**Human control** — human-in-the-loop at every uncertain boundary. The system asks when it's not confident rather than guessing.

**Observability** — every extraction and graph write is traced. The system shows its work.