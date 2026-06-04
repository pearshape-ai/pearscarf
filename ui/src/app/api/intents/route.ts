/**
 * GET /api/intents — list intents with sidecar state + child counts.
 *
 * Query params (all optional):
 *   status         — todo | in_progress | done | cancelled
 *   intent_type    — executor | coordinator
 *   runtime        — claude | codex | ...
 *   limit          — default 100, capped at 500
 */

import { NextRequest, NextResponse } from "next/server";
import { query } from "@/lib/db";

export const dynamic = "force-dynamic";

type Row = {
  id: string;
  created_at: string;
  set_at: string;
  set_by: string | null;
  status: string;
  intent_type: string;
  parent_record_id: string | null;
  owner: string | null;
  owner_role: string | null;
  runtime: string;
  runtime_config: Record<string, unknown>;
  depends_on: string[];
  body: string;
  child_total: number;
  child_done: number;
  child_in_flight: number;
};

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const status = searchParams.get("status");
  const intentType = searchParams.get("intent_type");
  const runtime = searchParams.get("runtime");
  const limit = Math.min(parseInt(searchParams.get("limit") || "100", 10), 500);

  const where: string[] = [];
  const params: unknown[] = [];
  if (status) {
    params.push(status);
    where.push(`d.status = $${params.length}`);
  }
  if (intentType) {
    params.push(intentType);
    where.push(`d.intent_type = $${params.length}`);
  }
  if (runtime) {
    params.push(runtime);
    where.push(`d.runtime = $${params.length}`);
  }
  const whereClause = where.length ? `WHERE ${where.join(" AND ")}` : "";
  params.push(limit);

  const sql = `
    SELECT
      r.id,
      r.created_at,
      d.set_at,
      d.set_by,
      d.status,
      d.intent_type,
      d.parent_record_id,
      d.owner,
      d.owner_role,
      d.runtime,
      d.runtime_config,
      d.depends_on,
      COALESCE(r.content, r.raw, '') AS body,
      COALESCE(c.total, 0)::int AS child_total,
      COALESCE(c.done, 0)::int AS child_done,
      COALESCE(c.in_flight, 0)::int AS child_in_flight
    FROM records r
    JOIN intent_details d ON d.intent_record_id = r.id
    LEFT JOIN LATERAL (
      SELECT
        COUNT(*) AS total,
        COUNT(*) FILTER (WHERE status = 'done') AS done,
        COUNT(*) FILTER (WHERE status IN ('todo', 'in_progress')) AS in_flight
      FROM intent_details
      WHERE parent_record_id = r.id
    ) c ON TRUE
    ${whereClause}
    ORDER BY r.created_at DESC
    LIMIT $${params.length}
  `;

  try {
    const rows = await query<Row>(sql, params);
    return NextResponse.json({ intents: rows });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
