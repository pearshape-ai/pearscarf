<p align="center">
  <img width="271" height="294" alt="PearScarf logo" src="https://github.com/user-attachments/assets/ecaf3cc6-a8a1-4af9-a5ee-545b7e9d38ef" />
</p>

<h1 align="center">PearScarf</h1>

<p align="center">
  Context engine for teams of agents.
</p>

<p align="center">
  <a href="docs/data-model.md">Data Model</a> · <a href="docs/query-surface.md">Query Surface</a> · <a href="docs/eval-metrics.md">Eval Metrics</a> · <a href="docs/getting-started.md">Getting Started</a> · <a href="docs/roadmap.md">Roadmap</a> · <a href="CHANGELOG.md">Changelog</a>
</p>

---

PearScarf is a self-improving, reality-aligned context engine for teams of agents, built on a bi-temporal knowledge graph.

It watches your data sources — Gmail, Linear, Slack, and more — extracts what matters, and makes it queryable by any agent in your system. One structured call. Sourced, dated, current context. No raw record processing on every run.

## Why current approaches fall short

Teams of agents deal with heterogeneous data — emails, issues, calendar, CRM — all connected in your head but siloed for your agents. Vector storage-based RAG loses those connections and when things happened. Stuffing raw records into context grows with every new source, and still leaves every agent rebuilding the same connections on every run.

## One call. Everything your agent needs to know.

PearScarf sits between your data sources and your agents. It observes records as they arrive, extracts structured facts with full provenance, and maintains those facts over time — nothing silently overwritten, history always preserved. When an agent needs context, it asks PearScarf. One call returns everything known about an entity: current state, recent activity, open commitments, blockers.

PearScarf is itself an agent — built and run as one. Its sole job is capturing and maintaining the state of the world so your other agents don't have to.

> **For OpenClaw and MCP-compatible frameworks**
>
> If your agents act but don't share memory, PearScarf is the missing piece. Connect once via MCP. Every agent in your system gets access to the same shared, up-to-date context — without you writing any retrieval logic.

## How it works

```
Data sources (Gmail, Linear, ...)
    ↓ polling
PearScarf observes → extracts entities & facts → maintains structured context
    ↓
Any agent queries via MCP
    ↓
Structured answer with provenance, confidence, and history
```

**Example — agent asking about a deal:**

```python
pearscarf.get_entity_context("Meridian Deal")
pearscarf.get_open_commitments(entity="Meridian Deal")
pearscarf.get_open_blockers(entity="Meridian Deal")

# Gets back
{
  "fact": "Marcus Webb to deliver contract markup by March 16",
  "fact_type": "commitment",
  "confidence": "stated",
  "valid_until": "2026-03-16",
  "source_url": "https://mail.google.com/..."
}
```

## What gets extracted — and how

PearScarf extracts two things from every record: entities and facts. Entities go into the graph as nodes. Facts connect them as edges.

Entities are the real-world things — people, companies, projects, events. Facts are what's known about them: who said what, what changed, who committed to what, and when.

Facts are extracted close to the source text — never summarised, never paraphrased. The original wording is preserved on every edge, with a direct link back to the source record. This keeps hallucination surface small: PearScarf connects and structures, it doesn't reinterpret.

Three fact types cover the operational world:

- **Affiliations** — who belongs to what (employee, founder, contributor, advisor, ...)
- **Assertions** — what was said or committed to (commitment, decision, blocker, risk, goal, ...)
- **Transitions** — what changed (status change, role change, completion, cancellation, ...)

See the [Data Model](docs/data-model.md) for the full schema and [Query Surface](docs/query-surface.md) for all available MCP tools.

## What's inside

- **Expert agents** — Gmail (OAuth API), Linear (GraphQL), more to come. Each owns its polling, schema, and extraction prompt.
- **Extraction pipeline** — LLM-powered entity and fact extraction from raw records, driven by editable prompts.
- **Temporal fact store** — Neo4j with bi-temporal fact edges and full provenance on every write. Postgres for structured records. Qdrant for semantic search.
- **MCP server** — read-only query surface. Any MCP-compatible agent framework connects once and queries for context.
- **Entity resolution** — alias accumulation, confidence scoring, human-in-the-loop for ambiguous cases.
- **Observability** — every LLM call and fact write traced via LangSmith.

## Quick start

```bash
uv sync
source .venv/bin/activate
playwright install chromium
docker compose up -d           # Postgres, Qdrant, Neo4j
cp .env.example .env           # add ANTHROPIC_API_KEY + POSTGRES_PASSWORD

psc gmail --auth               # Gmail OAuth setup
psc run                        # start the full system
psc run --poll-email           # start with automatic email polling
psc run --poll-linear          # start with automatic Linear polling
```

## Commands

| Command | Description |
|---|---|
| `psc run` | Worker + experts + session REPL |
| `psc run --poll-email` | Full system + email polling |
| `psc run --poll-linear` | Full system + Linear polling |
| `psc discord` | Worker + experts + Discord bot |
| `psc gmail --auth` | Gmail OAuth setup |
| `psc expert gmail` | Standalone Gmail expert |
| `psc expert linear` | Standalone Linear expert |
| `psc expert ingest --seed <file>` | Ingest a seed file |
| `psc eval --dataset <path>` | Run eval against a dataset |
| `psc memory entity "name"` | Look up entity + connections |
| `psc erase-all` | Wipe all system state |

## Docs

- [Data Model](docs/data-model.md) — entities, fact types, full schema, confidence values, bi-temporal model
- [Query Surface](docs/query-surface.md) — all MCP tools, inputs, outputs, output formats
- [Getting Started](docs/getting-started.md) — installation, Gmail OAuth, Docker setup
- [Eval Metrics](docs/eval-metrics.md) — extraction precision, recall, entity resolution accuracy
- [Roadmap](docs/roadmap.md) — verification agent, expert encapsulation, OpenClaw integration
- [Changelog](CHANGELOG.md)

---

Open source · Framework-agnostic · Built on Neo4j, Postgres, Qdrant