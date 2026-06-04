/**
 * GET /api/graph/stats — high-level graph stats for the dashboard header.
 *
 * Counts: entities (by label), edges (by edge label), facts (current vs stale).
 * Day nodes are excluded from the "entity" count — they're internal scaffolding.
 */

import { NextResponse } from "next/server";
import { cypher } from "@/lib/graph";

export const dynamic = "force-dynamic";

const ENTITY_LABELS = ["Person", "Company", "Project", "Event"];

export async function GET() {
  try {
    const [entitiesByLabel] = await Promise.all([
      cypher<{ label: string; count: number }>(
        `
        UNWIND $labels AS lbl
        CALL {
          WITH lbl
          MATCH (n) WHERE lbl IN labels(n)
          RETURN count(n) AS count
        }
        RETURN lbl AS label, count
        `,
        { labels: ENTITY_LABELS },
      ),
    ]);

    const factsByEdge = await cypher<{
      edge_label: string;
      total: number;
      current: number;
      stale: number;
    }>(
      `
      MATCH ()-[r]->()
      WHERE r.fact IS NOT NULL
      RETURN type(r) AS edge_label,
             count(r) AS total,
             count(CASE WHEN r.stale IS NULL OR r.stale = false THEN 1 END) AS current,
             count(CASE WHEN r.stale = true THEN 1 END) AS stale
      `,
    );

    const totalEntities = entitiesByLabel.reduce((s, e) => s + e.count, 0);
    const totalFacts = factsByEdge.reduce((s, e) => s + e.total, 0);
    const currentFacts = factsByEdge.reduce((s, e) => s + e.current, 0);
    const staleFacts = factsByEdge.reduce((s, e) => s + e.stale, 0);

    return NextResponse.json({
      totals: {
        entities: totalEntities,
        facts_total: totalFacts,
        facts_current: currentFacts,
        facts_stale: staleFacts,
      },
      by_label: entitiesByLabel,
      by_edge: factsByEdge,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
