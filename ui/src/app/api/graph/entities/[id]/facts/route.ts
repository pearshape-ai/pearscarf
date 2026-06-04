/**
 * GET /api/graph/entities/:id/facts — non-stale facts for one entity.
 *
 * Outgoing edges only — facts where this entity is the subject (what it
 * asserts / affiliates with / transitions to). Incoming edges properly
 * belong to the *other* entity's view; surfacing them here would mis-
 * attribute "X asserts Y" as a fact about Y when it's really a fact
 * about X.
 */

import { NextRequest, NextResponse } from "next/server";
import { cypher } from "@/lib/graph";

export const dynamic = "force-dynamic";

type EntityHeader = {
  id: string;
  label: string;
  name: string | null;
  aliases: string[];
};

type Fact = {
  edge_id: string;
  edge_label: string;
  fact_type: string | null;
  fact: string | null;
  confidence: string | null;
  source_at: string | null;
  source_record: string | null;
  source_type: string | null;
  recorded_at: string | null;
  other_id: string | null;
  other_name: string | null;
  other_label: string | null;
};

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;

  const headerSql = `
    MATCH (n) WHERE elementId(n) = $id
    OPTIONAL MATCH (n)-[ia:IDENTIFIED_AS]->()
    WITH n, labels(n) AS lbls, collect(DISTINCT ia.surface_form) AS aliases
    RETURN elementId(n) AS id,
           [l IN lbls WHERE l IN ['Person','Company','Project','Event']][0] AS label,
           n.name AS name,
           aliases
  `;

  const factsSql = `
    MATCH (n)-[r]->(other)
    WHERE elementId(n) = $id
      AND r.fact IS NOT NULL
      AND (r.stale IS NULL OR r.stale = false)
      AND type(r) <> 'IDENTIFIED_AS'
    RETURN elementId(r) AS edge_id,
           type(r) AS edge_label,
           r.fact_type AS fact_type,
           r.fact AS fact,
           r.confidence AS confidence,
           r.source_at AS source_at,
           r.source_record AS source_record,
           r.source_type AS source_type,
           r.recorded_at AS recorded_at,
           elementId(other) AS other_id,
           other.name AS other_name,
           [l IN labels(other) WHERE l IN ['Person','Company','Project','Event']][0] AS other_label
    ORDER BY r.source_at DESC
  `;

  try {
    const [[header], facts] = await Promise.all([
      cypher<EntityHeader>(headerSql, { id }),
      cypher<Fact>(factsSql, { id }),
    ]);
    if (!header) {
      return NextResponse.json({ error: "not_found", id }, { status: 404 });
    }
    return NextResponse.json({ entity: header, facts });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
