/**
 * Display helpers — relative time, token formatting, truncation.
 */

export function relativeTime(iso: string | Date): string {
  const date = typeof iso === "string" ? new Date(iso) : iso;
  const diff = (Date.now() - date.getTime()) / 1000;
  if (diff < 5) return "just now";
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return date.toISOString().slice(0, 10);
}

export function tokens(n: number | null | undefined): string {
  if (!n) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toString();
}

export function truncate(s: string | null | undefined, n: number): string {
  if (!s) return "";
  const collapsed = s.replace(/\s+/g, " ").trim();
  return collapsed.length <= n ? collapsed : collapsed.slice(0, n).trimEnd() + "…";
}
