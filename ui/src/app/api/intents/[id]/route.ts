/**
 * GET /api/intents/:id — full intent details + direct children list.
 */

import { NextRequest, NextResponse } from "next/server";
import { query } from "@/lib/db";

export const dynamic = "force-dynamic";

type Intent = {
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
  source: string;
};

type Child = {
  id: string;
  status: string;
  intent_type: string;
  owner: string | null;
  owner_role: string | null;
  runtime: string;
  body: string;
  set_at: string;
};

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;

  const intentSql = `
    SELECT
      r.id,
      r.created_at,
      r.source,
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
      COALESCE(r.content, r.raw, '') AS body
    FROM records r
    JOIN intent_details d ON d.intent_record_id = r.id
    WHERE r.id = $1
  `;
  const childrenSql = `
    SELECT
      r.id,
      d.status,
      d.intent_type,
      d.owner,
      d.owner_role,
      d.runtime,
      COALESCE(r.content, r.raw, '') AS body,
      d.set_at
    FROM records r
    JOIN intent_details d ON d.intent_record_id = r.id
    WHERE d.parent_record_id = $1
    ORDER BY r.created_at DESC
  `;

  try {
    const [[intent], children] = await Promise.all([
      query<Intent>(intentSql, [id]),
      query<Child>(childrenSql, [id]),
    ]);
    if (!intent) {
      return NextResponse.json({ error: "not_found", intent_id: id }, { status: 404 });
    }
    return NextResponse.json({ intent, children });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
