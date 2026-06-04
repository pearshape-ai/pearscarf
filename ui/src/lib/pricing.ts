/**
 * Hard-coded Claude pricing per million tokens (USD). Approximate — sourced
 * from publicly listed Anthropic pricing as of the v1 release. Update when
 * pricing changes or a new model shows up in PearScarf.
 */

type Pricing = {
  input: number;
  output: number;
  cacheRead: number;
  cacheCreation: number;
};

const PRICING: Record<string, Pricing> = {
  // Sonnet 4.x — typical executor model.
  "claude-sonnet-4-5": { input: 3, output: 15, cacheRead: 0.3, cacheCreation: 3.75 },
  "claude-sonnet-4-6": { input: 3, output: 15, cacheRead: 0.3, cacheCreation: 3.75 },
  // Opus 4.x — coordinator / heavier work.
  "claude-opus-4-6": { input: 15, output: 75, cacheRead: 1.5, cacheCreation: 18.75 },
  "claude-opus-4-7": { input: 15, output: 75, cacheRead: 1.5, cacheCreation: 18.75 },
  // Haiku 4.5 — light/fast.
  "claude-haiku-4-5": { input: 1, output: 5, cacheRead: 0.1, cacheCreation: 1.25 },
};

const FALLBACK: Pricing = { input: 3, output: 15, cacheRead: 0.3, cacheCreation: 3.75 };

export type TokenBreakdown = {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  model?: string | null;
};

function resolvePricing(model: string | null | undefined): Pricing {
  if (!model) return FALLBACK;
  // Exact match first.
  if (PRICING[model]) return PRICING[model];
  // Strip trailing `-YYYYMMDD` date suffix (Anthropic's snapshot ids).
  const stripped = model.replace(/-\d{8}$/, "");
  if (PRICING[stripped]) return PRICING[stripped];
  return FALLBACK;
}

export function estimateCostUsd(c: TokenBreakdown): number {
  const p = resolvePricing(c.model);
  return (
    (c.input_tokens * p.input) / 1_000_000 +
    (c.output_tokens * p.output) / 1_000_000 +
    (c.cache_read_tokens * p.cacheRead) / 1_000_000 +
    (c.cache_creation_tokens * p.cacheCreation) / 1_000_000
  );
}

export function formatUsd(n: number): string {
  if (n >= 1) return `$${n.toFixed(2)}`;
  if (n >= 0.01) return `$${n.toFixed(3)}`;
  if (n > 0) return `$${n.toFixed(4)}`;
  return "$0";
}
