/**
 * Singleton Neo4j driver, lazily initialized. Reads pearscarf's graph directly;
 * UI is read-only — no Cypher writes anywhere.
 */

import neo4j, { Driver, Integer } from "neo4j-driver";

declare global {
  // eslint-disable-next-line no-var
  var __neo4jDriver: Driver | undefined;
}

function driver(): Driver {
  if (!global.__neo4jDriver) {
    const url = process.env.NEO4J_URL;
    const user = process.env.NEO4J_USER;
    const password = process.env.NEO4J_PASSWORD;
    if (!url || !user || !password) {
      throw new Error("NEO4J_URL / NEO4J_USER / NEO4J_PASSWORD must all be set");
    }
    global.__neo4jDriver = neo4j.driver(url, neo4j.auth.basic(user, password), {
      maxConnectionPoolSize: 10,
      connectionAcquisitionTimeout: 10_000,
    });
  }
  return global.__neo4jDriver;
}

/** Run a single-shot read query; returns an array of plain JS objects. */
export async function cypher<T = Record<string, unknown>>(
  query: string,
  params: Record<string, unknown> = {},
): Promise<T[]> {
  const session = driver().session({ defaultAccessMode: neo4j.session.READ });
  try {
    const result = await session.run(query, params);
    return result.records.map((r) => normalize(r.toObject()) as T);
  } finally {
    await session.close();
  }
}

/** Recursively turn neo4j-driver's Integer + Node + Relationship wrappers into
 * plain JS so the result serializes cleanly to JSON. */
function normalize(value: unknown): unknown {
  if (value === null || value === undefined) return value;
  if (Integer.isInteger(value as Integer)) {
    // Coerce safely; entity counts and similar fit in Number.
    return (value as Integer).toNumber();
  }
  if (Array.isArray(value)) return value.map(normalize);
  if (typeof value !== "object") return value;

  // Neo4j Node / Relationship wrappers — flatten properties.
  const node = value as { labels?: string[]; properties?: Record<string, unknown>; type?: string; elementId?: string };
  if (node.labels && node.properties) {
    const props = normalize(node.properties) as Record<string, unknown>;
    return {
      __kind: "node",
      labels: node.labels,
      elementId: node.elementId,
      ...props,
    };
  }
  if (node.type && node.properties) {
    const props = normalize(node.properties) as Record<string, unknown>;
    return {
      __kind: "edge",
      type: node.type,
      elementId: node.elementId,
      ...props,
    };
  }

  // Plain object — recurse on values.
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    out[k] = normalize(v);
  }
  return out;
}
