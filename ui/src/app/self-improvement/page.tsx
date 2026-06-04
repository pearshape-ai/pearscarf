"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { tokens } from "@/lib/format";
import { formatUsd } from "@/lib/pricing";
import { relativeTime, truncate } from "@/lib/format";

const POLL_MS = parseInt(process.env.NEXT_PUBLIC_POLL_INTERVAL_MS || "4000", 10);

type Call = {
  id: number;
  created_at: string;
  consumer: string;
  agent_name: string;
  pearscarf_version: string;
  model: string;
  stop_reason: string;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  latency_ms: number | null;
  record_id: string | null;
  error: string | null;
  estimated_cost_usd: number;
};

type Totals = {
  count: number;
  records_processed: number;
  total_tokens: number;
  estimated_cost_usd: number;
  // Breakdown still available if a future view wants it.
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
};

async function fetchCalls(): Promise<{ calls: Call[]; totals: Totals }> {
  const res = await fetch("/api/llm-calls", { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function unifiedTokens(c: Call): number {
  return c.input_tokens + c.output_tokens + c.cache_creation_tokens + c.cache_read_tokens;
}

export default function SelfImprovementPage() {
  const { data, error, isLoading, dataUpdatedAt } = useQuery({
    queryKey: ["llm-calls"],
    queryFn: fetchCalls,
    refetchInterval: POLL_MS,
  });

  return (
    <div className="px-8 py-6">
      <header className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight">Self-improvement</h1>
        <p className="text-xs text-[color:var(--color-fg-subtle)] mt-1">
          What pearscarf&apos;s experts (extraction, curation, triage) are doing — and what it costs.
          {dataUpdatedAt ? ` Updated ${relativeTime(new Date(dataUpdatedAt))}.` : ""}
        </p>
      </header>

      {data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <Stat label="Records processed" value={data.totals.records_processed.toLocaleString()} />
          <Stat label="Cost" value={formatUsd(data.totals.estimated_cost_usd)} accent />
          <Stat label="Tokens" value={tokens(data.totals.total_tokens)} />
          <Stat label="Calls" value={data.totals.count.toLocaleString()} />
        </div>
      )}

      {error && (
        <div className="text-sm text-[color:var(--color-status-cancelled)] mb-4">
          {(error as Error).message}
        </div>
      )}

      <div className="border border-[color:var(--color-border)] rounded-md overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[color:var(--color-surface)] text-[color:var(--color-fg-muted)] text-xs uppercase tracking-wide">
            <tr>
              <th className="text-left px-4 py-2 font-medium w-24">When</th>
              <th className="text-left px-4 py-2 font-medium w-32">Consumer</th>
              <th className="text-left px-4 py-2 font-medium w-44">Model</th>
              <th className="text-right px-4 py-2 font-medium w-24">Tokens</th>
              <th className="text-right px-4 py-2 font-medium w-24">Cost</th>
              <th className="text-left px-4 py-2 font-medium w-28">Stop</th>
              <th className="text-right px-4 py-2 font-medium w-20">Latency</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-[color:var(--color-fg-subtle)]">
                  Loading…
                </td>
              </tr>
            )}
            {data?.calls.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-[color:var(--color-fg-subtle)]">
                  No calls yet.
                </td>
              </tr>
            )}
            {data?.calls.map((c) => (
              <tr
                key={c.id}
                className="border-t border-[color:var(--color-border)] bg-[color:var(--color-surface)] hover:bg-[color:var(--color-surface-hover)]"
              >
                <td className="px-4 py-2.5 text-xs text-[color:var(--color-fg-muted)]">
                  <Link href={`/llm-calls/${c.id}`} className="hover:underline">
                    {relativeTime(c.created_at)}
                  </Link>
                </td>
                <td className="px-4 py-2.5">
                  <span className="text-xs px-1.5 py-0.5 rounded bg-[color:var(--color-surface-hover)] text-[color:var(--color-fg-muted)] font-mono">
                    {c.consumer}
                  </span>
                  <span className="block text-[10px] text-[color:var(--color-fg-subtle)] mt-0.5">
                    {c.agent_name}
                  </span>
                </td>
                <td className="px-4 py-2.5 font-mono text-xs text-[color:var(--color-fg-muted)]">
                  {c.model}
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-xs">
                  {tokens(unifiedTokens(c))}
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-xs">
                  {formatUsd(c.estimated_cost_usd)}
                </td>
                <td className="px-4 py-2.5 text-xs text-[color:var(--color-fg-muted)]">
                  {c.error ? (
                    <span className="text-[color:var(--color-status-cancelled)]">error</span>
                  ) : (
                    truncate(c.stop_reason, 16)
                  )}
                </td>
                <td className="px-4 py-2.5 text-right text-xs text-[color:var(--color-fg-muted)]">
                  {c.latency_ms ? `${c.latency_ms}ms` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div
      className={`border rounded-md px-4 py-3 ${
        accent
          ? "border-[color:var(--color-accent)]/40 bg-[color:var(--color-accent)]/10"
          : "border-[color:var(--color-border)] bg-[color:var(--color-surface)]"
      }`}
    >
      <div className="text-xs text-[color:var(--color-fg-subtle)]">{label}</div>
      <div className="text-lg font-semibold tracking-tight mt-1">{value}</div>
    </div>
  );
}
