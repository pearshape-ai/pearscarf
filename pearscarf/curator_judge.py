"""Curator LLM judge for semantic equivalence of fact-edges."""

from __future__ import annotations

import json

import anthropic

from pearscarf import log
from pearscarf.config import ANTHROPIC_API_KEY, EXTRACTION_MODEL
from pearscarf.prompts import load as load_prompt
from pearscarf.tracing import trace_span


def judge_equivalence(
    candidates: list[dict],
    edge_label: str,
) -> list[list[str]]:
    """Call the LLM judge to group semantically equivalent edges.

    Returns list of lists of edge_id strings.
    On parse failure, returns each candidate in its own group (safe fallback).
    """
    if len(candidates) <= 1:
        return [[c["edge_id"]] for c in candidates]

    # Select prompt
    if edge_label == "AFFILIATED":
        system_prompt = load_prompt("curator_affiliated")
    else:
        # Placeholder for ASSERTED (1.14.3)
        return [[c["edge_id"]] for c in candidates]

    # Build user message
    lines = [f"Candidates for equivalence grouping ({len(candidates)}):"]
    for c in candidates:
        lines.append(
            f"  edge_id: {c['edge_id']}\n"
            f"  fact: {c['fact']}\n"
            f"  role: {c.get('role', '')}\n"
            f"  source_at: {c['source_at']}\n"
            f"  confidence: {c['confidence']}\n"
            f"  source_record: {c['source_record']}"
        )
        lines.append("")
    user_message = "\n".join(lines)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or None)

    with trace_span(
        "curator_judge",
        run_type="llm",
        metadata={"edge_label": edge_label, "candidate_count": len(candidates)},
        inputs={"prompt_length": len(user_message)},
    ) as span:
        response = client.messages.create(
            model=EXTRACTION_MODEL,
            max_tokens=512,
            temperature=0.0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        if span:
            span.end(outputs={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            })

    raw_text = ""
    for block in response.content:
        if block.type == "text":
            raw_text += block.text

    # Parse response
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[3:]
    if raw_text.endswith("```"):
        raw_text = raw_text[:-3]
    raw_text = raw_text.strip()

    try:
        groups = json.loads(raw_text)
        if isinstance(groups, list) and all(isinstance(g, list) for g in groups):
            return groups
    except json.JSONDecodeError:
        pass

    # Parse failure — safe fallback
    log.write(
        "curator", "--", "warning",
        f"curator_judge parse error for {edge_label} — treating all as distinct",
    )
    return [[c["edge_id"]] for c in candidates]
