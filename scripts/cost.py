"""Compute dollar cost of LLM calls logged to `llm_calls`.

Standalone utility — not a `psc` subcommand. Applies a hardcoded pricing table
to rows selected by the filter flags and prints per-call, per-record, and
summary sections.

Pearscarf deliberately does not compute dollars in-process (tokens stay as the
ground-truth unit, rates are applied externally). This script is the external
tool: rates live here, bump them when pricing moves.

Example:
    python scripts/cost.py --latest-eval
    python scripts/cost.py --runtime-id 5bdbfdd3-46d3-446b-a2ad-cc1a83c5cfa7
    python scripts/cost.py --since 2026-04-23T12:00 --consumer extraction
    python scripts/cost.py --record-id email_40058b7d --record-id email_df193d23 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load env before importing pearscarf.
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / "env/.env")

from pearscarf.storage.db import _get_conn  # noqa: E402


# Rates in $/M tokens. Rates as of 2026-04-23.
# Keyed by the exact `model` string logged to `llm_calls.model`.
# Anthropic: anthropic.com/pricing. OpenAI: openai.com/api/pricing.
# OpenAI doesn't charge a separate "cache_write" rate — prompt-cache writes
# are billed at the input rate, with cached reads discounted. We encode that
# by setting cache_write = input.
PRICES: dict[str, dict[str, float]] = {
    # --- Anthropic ---
    "claude-sonnet-4-5-20250929": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-haiku-4-5-20251001": {
        "input": 1.00,
        "output": 5.00,
        "cache_write": 1.25,
        "cache_read": 0.10,
    },
    # --- OpenAI ---
    "gpt-4o-mini": {
        "input": 0.15,
        "output": 0.60,
        "cache_write": 0.15,
        "cache_read": 0.075,
    },
    "gpt-4.1-mini": {
        "input": 0.40,
        "output": 1.60,
        "cache_write": 0.40,
        "cache_read": 0.10,
    },
    "gpt-4o": {
        "input": 2.50,
        "output": 10.00,
        "cache_write": 2.50,
        "cache_read": 1.25,
    },
    "gpt-5": {
        "input": 0.625,
        "output": 5.00,
        "cache_write": 0.625,
        "cache_read": 0.125,
    },
    "gpt-5-mini": {
        "input": 0.25,
        "output": 2.00,
        "cache_write": 0.25,
        "cache_read": 0.025,
    },
    "gpt-5-nano": {
        "input": 0.05,
        "output": 0.40,
        "cache_write": 0.05,
        "cache_read": 0.005,
    },
}


def _cost_of(row: dict) -> float | None:
    """Return dollars for one llm_calls row, or None for an unpriced model."""
    prices = PRICES.get(row["model"])
    if prices is None:
        return None
    return (
        row["input_tokens"] * prices["input"] / 1_000_000
        + row["output_tokens"] * prices["output"] / 1_000_000
        + row["cache_creation_tokens"] * prices["cache_write"] / 1_000_000
        + row["cache_read_tokens"] * prices["cache_read"] / 1_000_000
    )


def _build_query(args: argparse.Namespace) -> tuple[str, list]:
    where: list[str] = []
    params: list = []

    if args.record_id:
        where.append("record_id = ANY(%s)")
        params.append(args.record_id)
    if args.run_id:
        where.append("run_id = ANY(%s)")
        params.append(args.run_id)
    if args.session_id:
        where.append("session_id = ANY(%s)")
        params.append(args.session_id)
    if args.runtime_id:
        where.append("runtime_id = ANY(%s)")
        params.append(args.runtime_id)
    if args.consumer:
        where.append("consumer = %s")
        params.append(args.consumer)
    if args.model:
        where.append("model = %s")
        params.append(args.model)
    if args.since:
        where.append("created_at >= %s")
        params.append(args.since)
    if args.until:
        where.append("created_at < %s")
        params.append(args.until)

    if not where:
        sys.exit(
            "error: at least one filter flag is required "
            "(--record-id / --run-id / --session-id / --runtime-id / "
            "--consumer / --model / --since / --until / --latest-eval)"
        )

    sql = f"""
        SELECT id, created_at, runtime_id, consumer, agent_name, pearscarf_version,
               run_id, turn_index, provider, model, stop_reason, tool_calls,
               input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
               latency_ms, record_id, session_id
        FROM llm_calls
        WHERE {' AND '.join(where)}
        ORDER BY created_at, turn_index
    """
    return sql, params


def _resolve_latest_eval() -> str:
    """Find the most recent extraction runtime_id."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT runtime_id FROM llm_calls "
            "WHERE consumer = 'extraction' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            sys.exit("error: no extraction rows in llm_calls")
        return row["runtime_id"]


def _fetch(args: argparse.Namespace) -> list[dict]:
    sql, params = _build_query(args)
    with _get_conn() as conn:
        return list(conn.execute(sql, params).fetchall())


def _fmt_cost(cost: float | None) -> str:
    return f"${cost:.4f}" if cost is not None else "$?.????"


def _per_call_table(rows: list[dict]) -> None:
    print("=== Per call ===")
    print(
        f"{'created_at':<26} {'consumer':<12} {'model':<32} "
        f"{'run':<10} {'t':>2} {'in':>7} {'out':>6} {'cost':>9}"
    )
    for r in rows:
        run = (r["run_id"] or "")[:8]
        print(
            f"{r['created_at'].isoformat():<26} "
            f"{r['consumer']:<12} {r['model']:<32} "
            f"{run:<10} {r['turn_index']:>2} "
            f"{r['input_tokens']:>7,} {r['output_tokens']:>6,} "
            f"{_fmt_cost(_cost_of(r)):>9}"
        )


def _rollup_per_record(rows: list[dict]) -> dict[str, dict]:
    groups: dict[str, dict] = defaultdict(
        lambda: {
            "turns": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cost": 0.0,
            "cost_known": True,
            "models": set(),
            "kind": None,
        }
    )
    for r in rows:
        key = r["record_id"] or r["session_id"]
        if key is None:
            continue
        g = groups[key]
        g["kind"] = "record_id" if r["record_id"] else "session_id"
        g["turns"] += 1
        g["input_tokens"] += r["input_tokens"]
        g["output_tokens"] += r["output_tokens"]
        g["cache_creation_tokens"] += r["cache_creation_tokens"]
        g["cache_read_tokens"] += r["cache_read_tokens"]
        g["models"].add(r["model"])
        cost = _cost_of(r)
        if cost is None:
            g["cost_known"] = False
        else:
            g["cost"] += cost
    return groups


def _per_record_table(groups: dict[str, dict]) -> None:
    if not groups:
        return
    print()
    any_kind = next(iter(groups.values()))["kind"]
    print(f"=== Per {any_kind} ===")
    print(f"{'id':<32} {'turns':>5} {'in':>9} {'out':>7} {'cost':>9}")
    for key, g in sorted(groups.items(), key=lambda x: -x[1]["cost"]):
        cost_str = f"${g['cost']:.4f}" if g["cost_known"] else f"~${g['cost']:.4f}"
        print(
            f"{key:<32} {g['turns']:>5} "
            f"{g['input_tokens']:>9,} {g['output_tokens']:>7,} "
            f"{cost_str:>9}"
        )


def _summary(rows: list[dict]) -> dict:
    total = {
        "calls": len(rows),
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "cost": 0.0,
        "unknown_models": set(),
    }
    by_model: dict[str, dict] = defaultdict(
        lambda: {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "cost": 0.0,
            "priced": True,
        }
    )
    for r in rows:
        total["input_tokens"] += r["input_tokens"]
        total["output_tokens"] += r["output_tokens"]
        total["cache_creation_tokens"] += r["cache_creation_tokens"]
        total["cache_read_tokens"] += r["cache_read_tokens"]
        m = by_model[r["model"]]
        m["calls"] += 1
        m["input_tokens"] += r["input_tokens"]
        m["output_tokens"] += r["output_tokens"]
        m["cache_creation_tokens"] += r["cache_creation_tokens"]
        m["cache_read_tokens"] += r["cache_read_tokens"]
        cost = _cost_of(r)
        if cost is None:
            total["unknown_models"].add(r["model"])
            m["priced"] = False
        else:
            total["cost"] += cost
            m["cost"] += cost
    return {"total": total, "by_model": dict(by_model)}


def _summary_table(summary: dict) -> None:
    t = summary["total"]
    print()
    print("=== Summary ===")
    print(f"  Calls:               {t['calls']}")
    print(f"  Input tokens:        {t['input_tokens']:,}")
    print(f"  Output tokens:       {t['output_tokens']:,}")
    print(f"  Cache creation:      {t['cache_creation_tokens']:,}")
    print(f"  Cache read:          {t['cache_read_tokens']:,}")
    print(f"  Total cost:          ${t['cost']:.4f}")
    if t["unknown_models"]:
        print(
            f"  Unpriced models:     {', '.join(sorted(t['unknown_models']))} "
            f"(bump PRICES table in scripts/cost.py)"
        )
    print()
    print("  By model:")
    for m_name, m in summary["by_model"].items():
        flag = "" if m["priced"] else " (unpriced)"
        print(
            f"    {m_name}: {m['calls']} calls, "
            f"{m['input_tokens']:,} in + {m['output_tokens']:,} out, "
            f"${m['cost']:.4f}{flag}"
        )


def _json_output(rows: list[dict], groups: dict[str, dict], summary: dict) -> None:
    def default(o: Any):
        if hasattr(o, "isoformat"):
            return o.isoformat()
        if isinstance(o, set):
            return sorted(o)
        raise TypeError(f"not serializable: {type(o)}")

    payload = {
        "summary": {
            "total": summary["total"],
            "by_model": summary["by_model"],
        },
        "per_record": {
            k: {**g, "models": sorted(g["models"])} for k, g in groups.items()
        },
        "calls": [
            {k: v for k, v in r.items() if k != "tool_calls"} | {
                "tool_calls": r["tool_calls"],
                "cost": _cost_of(r),
            }
            for r in rows
        ],
    }
    print(json.dumps(payload, default=default, indent=2))


def main() -> int:
    p = argparse.ArgumentParser(
        description="Compute dollar cost of llm_calls rows.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--record-id", action="append", help="Repeatable.")
    p.add_argument("--run-id", action="append", help="Repeatable.")
    p.add_argument("--session-id", action="append", help="Repeatable.")
    p.add_argument("--runtime-id", action="append", help="Repeatable.")
    p.add_argument("--consumer", help="e.g. extraction, triage, assistant.")
    p.add_argument("--model", help="Filter to one model ID.")
    p.add_argument("--since", help="ISO-8601 inclusive lower bound on created_at.")
    p.add_argument("--until", help="ISO-8601 exclusive upper bound on created_at.")
    p.add_argument(
        "--latest-eval",
        action="store_true",
        help="Shortcut: most recent extraction runtime.",
    )
    p.add_argument("--no-per-call", action="store_true", help="Suppress per-call detail.")
    p.add_argument("--no-per-record", action="store_true", help="Suppress per-record rollup.")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of tables.")
    args = p.parse_args()

    if args.latest_eval:
        rt = _resolve_latest_eval()
        args.runtime_id = (args.runtime_id or []) + [rt]

    rows = _fetch(args)
    if not rows:
        print("No llm_calls rows matched.")
        return 0

    groups = _rollup_per_record(rows)
    summary = _summary(rows)

    if args.json:
        _json_output(rows, groups, summary)
        return 0

    if not args.no_per_call:
        _per_call_table(rows)
    if not args.no_per_record:
        _per_record_table(groups)
    _summary_table(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
