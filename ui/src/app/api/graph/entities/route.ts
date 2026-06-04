/**
 * GET /api/graph/entities — list entities with non-stale fact counts.
 *
 * Query params:
 *   label   — Person | Company | Project | Event (optional; one of)
 *   limit   — default 100, capped at 500
 */

import { NextRequest, NextResponse } from "next/server";
import { cypher } from "@/lib/graph";

export const dynamic = "force-dynamic";

const ALLOWED = ["Person", "Company", "Project", "Event"] as const;

type EntityRow = {
  id: string;
  label: string;
  name: string | null;
  created_at: string | null;
  fact_count: number;
  most_recent_source_at: string | null;
  aliases: string[];
};

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const label = searchParams.get("label");
  const limit = Math.min(parseInt(searchParams.get("limit") || "100", 10), 500);

  const labelFilter = label && (ALLOWED as readonly string[]).includes(label) ? label : null;

  const labelClause = labelFilter
    ? `MATCH (n:${labelFilter})`
    : `MATCH (n) WHERE ANY(l IN labels(n) WHERE l IN $allowed)`;

  // LIMIT is inlined (already integer-validated above) to avoid neo4j-driver's
  // JS-Number → Cypher-int coercion quirk for the LIMIT clause.
  const query = `
    ${labelClause}
    OPTIONAL MATCH (n)-[r]-() WHERE r.fact IS NOT NULL AND (r.stale IS NULL OR r.stale = false)
    OPTIONAL MATCH (n)-[id:IDENTIFIED_AS]->()
    WITH n,
         labels(n) AS lbls,
         count(DISTINCT r) AS fact_count,
         max(r.source_at) AS most_recent_source_at,
         collect(DISTINCT id.surface_form) AS aliases
    RETURN elementId(n) AS id,
           [l IN lbls WHERE l IN $allowed][0] AS label,
           n.name AS name,
           n.created_at AS created_at,
           fact_count,
           most_recent_source_at,
           aliases
    ORDER BY most_recent_source_at IS NULL ASC, most_recent_source_at DESC, n.created_at DESC
    LIMIT ${limit}
  `;

  try {
    const rows = await cypher<EntityRow>(query, { allowed: ALLOWED });
    return NextResponse.json({ entities: rows });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
