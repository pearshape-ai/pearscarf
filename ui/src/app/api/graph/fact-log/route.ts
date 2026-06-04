/**
 * GET /api/graph/fact-log — every fact in the graph, newest first.
 *
 * A reverse-chronological log of operational deltas: one row per fact-edge,
 * ordered by `recorded_at` (when the fact landed in Neo4j) rather than
 * `source_at` (when the fact was true in the world). Returns the *full* log,
 * including superseded/stale facts — a supersession is itself a delta worth
 * seeing scroll by. Both endpoints of each edge are returned so the log reads
 * "subject → target" without a second lookup.
 */

import { NextResponse } from "next/server";
import { cypher } from "@/lib/graph";

export const dynamic = "force-dynamic";

type FactLogEntry = {
  edge_id: string;
  edge_label: string;
  fact_type: string | null;
  fact: string | null;
  confidence: string | null;
  source_at: string | null;
  recorded_at: string | null;
  source_record: string | null;
  source_type: string | null;
  stale: boolean;
  subject_id: string | null;
  subject_name: string | null;
  subject_labels: string[];
  other_id: string | null;
  other_name: string | null;
  other_labels: string[];
};

const SQL = `
  MATCH (subj)-[r]->(obj)
  WHERE r.fact IS NOT NULL AND type(r) <> 'IDENTIFIED_AS'
  RETURN elementId(r) AS edge_id,
         type(r) AS edge_label,
         r.fact_type AS fact_type,
         r.fact AS fact,
         r.confidence AS confidence,
         r.source_at AS source_at,
         r.recorded_at AS recorded_at,
         r.source_record AS source_record,
         r.source_type AS source_type,
         coalesce(r.stale, false) AS stale,
         elementId(subj) AS subject_id,
         coalesce(subj.name, subj.date) AS subject_name,
         labels(subj) AS subject_labels,
         elementId(obj) AS other_id,
         coalesce(obj.name, obj.date) AS other_name,
         labels(obj) AS other_labels
  ORDER BY coalesce(r.recorded_at, r.source_at, '') DESC
`;

export async function GET() {
  try {
    const facts = await cypher<FactLogEntry>(SQL);
    return NextResponse.json({ facts, count: facts.length });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
