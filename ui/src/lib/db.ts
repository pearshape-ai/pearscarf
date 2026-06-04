/**
 * Singleton Postgres pool, lazily initialized. Reads pearscarf's database
 * directly — UI is read-only, no writes.
 */

import { Pool } from "pg";

declare global {
  // eslint-disable-next-line no-var
  var __pgPool: Pool | undefined;
}

export function pool(): Pool {
  if (!global.__pgPool) {
    const url = process.env.DATABASE_URL;
    if (!url) {
      throw new Error(
        "DATABASE_URL is not set — pearscarf-ui reads pearscarf's postgres directly.",
      );
    }
    global.__pgPool = new Pool({
      connectionString: url,
      max: 5,
      idleTimeoutMillis: 30_000,
      // Reasonable defaults for read-only dashboard usage.
    });
  }
  return global.__pgPool;
}

export async function query<T extends Record<string, unknown>>(
  text: string,
  params?: unknown[],
): Promise<T[]> {
  const res = await pool().query(text, params);
  return res.rows as T[];
}
