/**
 * GET /api/llm-calls/:id — full call + joined prompt body.
 */

import { NextRequest, NextResponse } from "next/server";
import { query } from "@/lib/db";
import { estimateCostUsd } from "@/lib/pricing";

export const dynamic = "force-dynamic";

type Row = {
  id: number;
  created_at: string;
  runtime_id: string;
  consumer: string;
  agent_name: string;
  pearscarf_version: string;
  run_id: string;
  turn_index: number;
  provider: string;
  model: string;
  prompt_hash: string;
  prompt_body: string;
  stop_reason: string;
  tool_calls: unknown;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  latency_ms: number | null;
  record_id: string | null;
  session_id: string | null;
  error: string | null;
  input_messages: unknown;
  response_text: string | null;
  response_tool_calls: unknown;
};

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const callId = parseInt(id, 10);
  if (!Number.isFinite(callId)) {
    return NextResponse.json({ error: "invalid id" }, { status: 400 });
  }

  const sql = `
    SELECT
      c.id, c.created_at, c.runtime_id, c.consumer, c.agent_name,
      c.pearscarf_version, c.run_id, c.turn_index, c.provider, c.model,
      c.prompt_hash, p.body AS prompt_body, c.stop_reason, c.tool_calls,
      c.input_tokens, c.output_tokens, c.cache_creation_tokens,
      c.cache_read_tokens, c.latency_ms, c.record_id, c.session_id, c.error,
      c.input_messages, c.response_text, c.response_tool_calls
    FROM llm_calls c
    LEFT JOIN llm_prompts p ON p.hash = c.prompt_hash
    WHERE c.id = $1
  `;

  try {
    const [row] = await query<Row>(sql, [callId]);
    if (!row) {
      return NextResponse.json({ error: "not_found", id: callId }, { status: 404 });
    }
    return NextResponse.json({
      ...row,
      estimated_cost_usd: estimateCostUsd({
        input_tokens: row.input_tokens,
        output_tokens: row.output_tokens,
        cache_read_tokens: row.cache_read_tokens,
        cache_creation_tokens: row.cache_creation_tokens,
        model: row.model,
      }),
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
