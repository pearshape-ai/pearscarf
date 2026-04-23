# scripts/

Standalone utilities. Not `psc` subcommands — invoked directly with `python scripts/<name>.py` or `uv run python scripts/<name>.py`.

## cost.py

Computes dollar cost of LLM calls logged to `llm_calls`. Applies a hardcoded pricing table (bump the `PRICES` dict when rates move). Prints per-call, per-record, and summary sections; add `--json` for machine-readable output.

At least one filter flag is required. Common uses:

```bash
# Latest extraction run (ER eval, ad-hoc extraction).
python scripts/cost.py --latest-eval

# Specific runtime (e.g., a named baseline captured in a lab file).
python scripts/cost.py --runtime-id 9cef59fa-c553-42c8-9e09-7895443850c9

# A set of records you care about.
python scripts/cost.py --record-id email_40058b7d --record-id linear_issue_24e978eb

# Time window + consumer.
python scripts/cost.py --since 2026-04-23T12:00 --consumer extraction

# Suppress verbose sections.
python scripts/cost.py --latest-eval --no-per-call

# JSON for piping.
python scripts/cost.py --latest-eval --json | jq '.summary.total.cost'
```

Unknown models (no entry in `PRICES`) print as `$?.????` and are flagged in the summary — no silent misattribution.

## erase_all.py

Wipes all system state — Postgres `records` + typed tables, Neo4j graph, Qdrant vectors. Does **not** touch observability tables (`llm_calls`, `llm_prompts`, `runtimes`) — baseline cost/quality data is preserved across evals. Prompts interactively before deleting.

```bash
python scripts/erase_all.py
echo y | python scripts/erase_all.py   # skip the confirm prompt
```

## reindex_all.py

Resets the `indexed` flag on existing records without deleting them. Use when extraction prompts or tools change and you want to re-extract against current behavior.

```bash
python scripts/reindex_all.py
```
