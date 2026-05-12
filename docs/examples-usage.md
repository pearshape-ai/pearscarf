# Examples & Usage

PearScarf accepts records from three source patterns. Pick the one that matches your use case — they're complementary, not exclusive.

| Source pattern | When to use | Where to look |
|---|---|---|
| **Push from your agent** | An LLM agent, custom tool, or human-in-loop captures work outcomes (decisions, ships, escalations) | [§1 below](#1-pushing-records-from-your-agent) |
| **Poll an external system** | An existing system (Linear, Gmail, GitHub) is the source of truth for some part of your work | [§2 below](#2-polling-external-systems) |
| **Add your own source** | Your source isn't covered by built-ins | [§3 below](#3-adding-your-own-source-expert) |

All three converge: the record body has the same shape, extraction goes through the same pipeline, the graph reads back identically regardless of how the record arrived.

---

## 1. Pushing records from your agent

**The recommended starting point.** Any client that speaks MCP can submit a record to PearScarf via the `submit_record` tool — LLM agents (Claude, GPT, custom), human-in-loop tools, scripts.

### The body shape

A record is markdown with a fixed top-to-bottom structure:

````
Title: <single-line title>

Id: <unique stable identifier>
Date: <YYYY-MM-DD>

<Anchor line — convention varies by scope; e.g. "Shipped in v1.2.3.">

## For humans

<1–3 paragraphs of brief narrative — what changed/decided, why.>

## For agents

```yaml
facts:
  - "<one rich sentence stating one fact>"
  - "<another fact, same shape>"
```
````

The canonical spec lives at [`pearscarf/knowledge/records/format.md`](../pearscarf/knowledge/records/format.md) and is also served as the MCP resource `pearscarf://format/record` — your agent can fetch it before its first submission.

### Submitting

Any MCP client calls:

```python
submit_record(
    body=record_body_markdown,
    url="https://your-system.com/path/to/this-record",
    op_area="reality",  # routing — see below
)
# returns: {"record_id": "record_xxxxx", "status": "queued"}
```

**`op_area`** is record-level routing.

- **`reality`** (default) — the record describes something observed, shipped, deployed, signed, sent. PearScarf triages and extracts it, and its facts land in the graph. The graph is reality-only.
- **`intent`** — the record describes a plan or commitment, not an observed fact. PearScarf persists the record but skips the graph. A dedicated submission surface for intents is coming separately; for now, `op_area="intent"` records are accepted but do not yet have a downstream consumer beyond persistence.

Poll `get_record_status(record_id)` until `status == "indexed"` — at that point reality facts are in the graph and queryable via the read tools.

### Worked example

A planning agent at Acme picks a database for a new feature and records the decision so future sessions don't re-litigate it:

````
Title: Pick Postgres over DynamoDB for the audit-log feature

Id: 20260512-audit-log-db-decision
Date: 2026-05-12

Decided in lab/design/audit-log-store.md.

## For humans

The audit-log feature needs ACID writes across user + event tables and ad-hoc
date-range queries from the ops dashboard. We considered DynamoDB (lower ops
overhead, fits the access pattern) but its lack of transactional joins would
push correctness logic into the application layer, undoing the simplicity.
Postgres handles both with no extra moving parts; we already operate it.

## For agents

```yaml
facts:
  - "Acme picked Postgres as the store for the audit-log feature, choosing transactional writes and ad-hoc joins over DynamoDB's lower ops overhead — Postgres handles both natively with no extra moving parts."
```
````

Submit-time: `url: "https://github.com/acme/eng-decisions/blob/main/20260512-audit-log-db-decision.md"`, `op_area: "reality"`.

After extraction completes, querying the graph for `Acme` returns the decision; querying for `Postgres` returns it too. A future planning session asking "have we picked a store for audit-log?" lands the answer in one call.

### Why this is the recommended starting point

- **No system-specific glue.** Whatever captures the work outcome can submit. No Linear API, no GitHub webhook, no IMAP — just MCP.
- **Author discipline > extraction inference.** The author knows which facts matter; pearscarf reads them as authored rather than guessing from prose.
- **Clean provenance.** Every fact carries the `source_url` you supply — the canonical link back to where the record lives.

---

## 2. Polling external systems

If the source of truth for part of your work already lives in Linear, Gmail, or GitHub, install the built-in source expert and let it pick up changes automatically.

### Available experts

| Expert | Source | Record types |
|---|---|---|
| `linearscarf` | Linear (issues, comments, status changes) | `linear_issue`, `linear_issue_change` |
| `gmailscarf` | Gmail threads (configured labels) | `email` |
| `githubscarf` | GitHub (PRs, issues) | `github_pr`, `github_issue` |

Each ships in `experts/<name>/` with its own README, `.env.example`, and ingester.

### Installing and configuring

```bash
# install (registers the expert with pearscarf's registry)
psc expert install experts/linearscarf

# configure
cp experts/linearscarf/.env.example env/.linearscarf.env
$EDITOR env/.linearscarf.env  # add LINEAR_API_KEY, LINEAR_WORKSPACE_ID

# run the ingester (foreground)
psc expert start-ingestion linearscarf
```

The ingester polls the configured source on its own cadence, normalizes each item to the expert's record shape, and submits via the same pipeline that agentic submissions (§1) use.

### Worked example

Acme installs `linearscarf` against their `Acme Eng` workspace. On startup, it walks recent issue activity (default: last 7 days) and submits each issue + each status change as separate records. PearScarf extracts:

- A `Project` for each Linear project (e.g. `Acme API Integration`)
- A `Person` for each assignee/commenter (with their email when known)
- A `commitment` fact per `Status: In Progress → Done` transition, with the issue title in the fact text
- A `blocker` fact when an issue body contains explicit blocker language

Ongoing: linearscarf re-polls every N minutes, dedups against the graph (records already extracted are skipped), and surfaces only what's new. Querying `get_entity_context(entity_name="Acme API Integration")` returns the project's open commitments, recent activity, and current blockers — all sourced from Linear, kept fresh without any agent intervention.

### When this path is right

- The source already contains the structured signal you want.
- You don't want to rewrite or duplicate that signal somewhere else.
- You're willing to operate one polling loop per source.

### When this path is *not* right

- The source is the agent itself. Use §1 — it's cheaper and more direct.
- The signal you care about isn't well-modeled by the source's data shape (e.g. you want "decisions" but the source only has "issues"). Add a custom expert (§3) that reshapes the source.

---

## 3. Adding your own source expert

When neither agentic submission nor a built-in expert fits — typically because you have a source that's not Linear/Gmail/GitHub but holds structured signal worth capturing.

### Expert anatomy

An expert is a Python package with three things:

1. **Manifest** (`manifest.yaml`) — declares record types, knowledge dir, ingester module path
2. **Ingester** — a Python class that polls the source, normalizes each item to a record body, and submits via the standard pipeline
3. **Knowledge** (`knowledge/`) — markdown files describing source-specific extraction guidance (`extraction.md`), per-source relevancy hints (`relevancy.md`), and an optional agent prompt (`agent.md`)

### Minimal scaffold

For a hypothetical `notion-pages` expert that ingests pages from a Notion workspace:

```yaml
# experts/notion-pages/manifest.yaml
name: notion-pages
version: "0.1.0"
record_types:
  - notion_page
knowledge: experts/notion-pages/knowledge
ingester: experts/notion-pages/ingester.py
```

```python
# experts/notion-pages/ingester.py
from pearscarf.experts.base import BaseIngester

class NotionPagesIngester(BaseIngester):
    record_type = "notion_page"

    def poll(self):
        # call Notion API, yield each page as (record_id, body, source_url)
        for page in self._notion_client.list_pages(since=self.last_polled):
            body = self._format_record(page)
            yield (page.id, body, page.public_url)

    def _format_record(self, page):
        return f"""\
Title: {page.title}

Id: notion-{page.id}
Date: {page.last_edited:%Y-%m-%d}

Notion page in workspace {self._notion_client.workspace_name}.

## For humans

{page.summary}

## For agents

```yaml
facts:
  - "..."  # facts the page author committed to
```
"""
```

```markdown
# experts/notion-pages/knowledge/extraction.md

You are processing a Notion page from the Acme team's workspace. Pages in
the "Decisions" database commit to a structured `## For agents` block —
extract those facts as authored. Pages in other databases use freer prose;
extract only entities and facts that match the canonical types.
```

### Worked example

Acme keeps a "Decisions" database in Notion. They write a `notion-pages` expert that polls the Decisions database hourly. Each page becomes a `notion_page` record. PearScarf extracts the decisions into the graph alongside Linear-issue commitments and email-thread commitments — all queryable from the same `get_entity_context(entity_name="Acme API Integration")` call. A planning agent later asks "has Acme decided on a vendor?" and gets the Notion-sourced decision in the same response as the Linear-sourced commitments.

### When you'll need to extend further

- **Different transports.** Webhook-driven instead of polling? Override `BaseIngester.run()` and call `self.submit_record(...)` from your handler.
- **Multiple record types per source.** Declare them all in `record_types` and dispatch in your ingester.
- **Source-specific extraction guidance.** Drop `experts/<name>/knowledge/extraction.md` — it gets injected into the extractor prompt for records of your `record_type`.

The full reference for the expert contract, including ingester base class, manifest schema, and lifecycle hooks, lives in [`docs/expert_guide.md`](expert_guide.md).

---

## See also

- [`README.md`](../README.md) — install + run, in 30 seconds
- [`docs/architecture.md`](architecture.md) — how the pipeline works under the hood
- [`docs/expert_guide.md`](expert_guide.md) — full reference for building a source expert
- [`docs/getting-started.md`](getting-started.md) — first-time setup walk-through
- [`pearscarf/knowledge/records/format.md`](../pearscarf/knowledge/records/format.md) — full record format spec
