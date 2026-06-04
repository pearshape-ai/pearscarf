/**
 * GET /api/llm-calls — list LLM calls + aggregate totals (tokens + cost).
 *
 * Query params (all optional):
 *   consumer   — extraction | curation | triage | ...
 *   model      — exact model id
 *   limit      — default 100, capped at 500
 */

import { NextRequest, NextResponse } from "next/server";
import { query } from "@/lib/db";
import { estimateCostUsd } from "@/lib/pricing";

export const dynamic = "force-dynamic";

type CallRow = {
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
  stop_reason: string;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  latency_ms: number | null;
  record_id: string | null;
  session_id: string | null;
  error: string | null;
};

type TotalsRow = {
  count: string;
  input_tokens: string | null;
  output_tokens: string | null;
  cache_creation_tokens: string | null;
  cache_read_tokens: string | null;
  records_processed: string;
};

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const consumer = searchParams.get("consumer");
  const model = searchParams.get("model");
  const limit = Math.min(parseInt(searchParams.get("limit") || "100", 10), 500);

  const where: string[] = [];
  const params: unknown[] = [];
  if (consumer) {
    params.push(consumer);
    where.push(`consumer = $${params.length}`);
  }
  if (model) {
    params.push(model);
    where.push(`model = $${params.length}`);
  }
  const whereClause = where.length ? `WHERE ${where.join(" AND ")}` : "";

  const callsParams = [...params, limit];
  const callsSql = `
    SELECT
      id, created_at, runtime_id, consumer, agent_name, pearscarf_version,
      run_id, turn_index, provider, model, prompt_hash, stop_reason,
      input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
      latency_ms, record_id, session_id, error
    FROM llm_calls
    ${whereClause}
    ORDER BY created_at DESC
    LIMIT $${callsParams.length}
  `;

  // Aggregate over the same filter set (NOT limited). `records_processed`
  // counts distinct records — multiple turns on one record collapse to one.
  const totalsSql = `
    SELECT
      COUNT(*) AS count,
      SUM(input_tokens) AS input_tokens,
      SUM(output_tokens) AS output_tokens,
      SUM(cache_creation_tokens) AS cache_creation_tokens,
      SUM(cache_read_tokens) AS cache_read_tokens,
      COUNT(DISTINCT record_id) FILTER (WHERE record_id IS NOT NULL) AS records_processed
    FROM llm_calls
    ${whereClause}
  `;

  try {
    const [calls, [tot]] = await Promise.all([
      query<CallRow>(callsSql, callsParams),
      query<TotalsRow>(totalsSql, params),
    ]);

    // Compute cost per row + aggregate.
    const callsWithCost = calls.map((c) => ({
      ...c,
      estimated_cost_usd: estimateCostUsd({
        input_tokens: c.input_tokens,
        output_tokens: c.output_tokens,
        cache_read_tokens: c.cache_read_tokens,
        cache_creation_tokens: c.cache_creation_tokens,
        model: c.model,
      }),
    }));

    // Aggregate cost requires per-model accounting (different model = different
    // price). Group the filtered set by model and sum.
    const byModelSql = `
      SELECT
        model,
        SUM(input_tokens)::int AS input_tokens,
        SUM(output_tokens)::int AS output_tokens,
        SUM(cache_creation_tokens)::int AS cache_creation_tokens,
        SUM(cache_read_tokens)::int AS cache_read_tokens
      FROM llm_calls
      ${whereClause}
      GROUP BY model
    `;
    const byModel = await query<{
      model: string;
      input_tokens: number;
      output_tokens: number;
      cache_creation_tokens: number;
      cache_read_tokens: number;
    }>(byModelSql, params);
    const aggregateCost = byModel.reduce(
      (sum, row) => sum + estimateCostUsd(row),
      0,
    );

    const totalInputTokens = parseInt(tot?.input_tokens ?? "0", 10);
    const totalOutputTokens = parseInt(tot?.output_tokens ?? "0", 10);
    const totalCacheCreate = parseInt(tot?.cache_creation_tokens ?? "0", 10);
    const totalCacheRead = parseInt(tot?.cache_read_tokens ?? "0", 10);

    return NextResponse.json({
      calls: callsWithCost,
      totals: {
        count: parseInt(tot?.count ?? "0", 10),
        records_processed: parseInt(tot?.records_processed ?? "0", 10),
        // Unified token count — same number the cost calculation aggregates over.
        total_tokens: totalInputTokens + totalOutputTokens + totalCacheCreate + totalCacheRead,
        estimated_cost_usd: aggregateCost,
        // Breakdown still surfaced for the per-call detail page.
        input_tokens: totalInputTokens,
        output_tokens: totalOutputTokens,
        cache_creation_tokens: totalCacheCreate,
        cache_read_tokens: totalCacheRead,
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
