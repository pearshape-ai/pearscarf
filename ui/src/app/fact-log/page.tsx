"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { relativeTime } from "@/lib/format";

// Snappier than the rest of the app — this page is about watching facts land.
const POLL_MS = 2000;

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

async function fetchFactLog(): Promise<{ facts: FactLogEntry[]; count: number }> {
  const res = await fetch("/api/graph/fact-log", { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

const KNOWN_LABELS = ["Person", "Company", "Project", "Event"];

function displayLabel(labels: string[]): string | null {
  if (!labels || labels.length === 0) return null;
  return labels.find((l) => KNOWN_LABELS.includes(l)) ?? labels[0];
}

const EDGE_COLOR: Record<string, string> = {
  ASSERTED: "var(--color-accent)",
  AFFILIATED: "var(--color-type-coordinator)",
  TRANSITIONED: "var(--color-status-in-progress)",
};

function prettyEdge(edge: string): string {
  switch (edge) {
    case "AFFILIATED":
      return "Affiliated";
    case "ASSERTED":
      return "Asserted";
    case "TRANSITIONED":
      return "Transitioned";
    default:
      return edge.toLowerCase().replace(/_/g, " ");
  }
}

export default function FactLogPage() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["fact-log"],
    queryFn: fetchFactLog,
    refetchInterval: POLL_MS,
  });

  // Track which edge_ids we've already shown, so only facts that arrive
  // *after* first load animate in (the initial batch shouldn't all flash).
  const seenRef = useRef<Set<string>>(new Set());
  const initializedRef = useRef(false);
  const [newIds, setNewIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!data) return;
    const ids = data.facts.map((f) => f.edge_id);
    if (!initializedRef.current) {
      ids.forEach((id) => seenRef.current.add(id));
      initializedRef.current = true;
      return;
    }
    const fresh = ids.filter((id) => !seenRef.current.has(id));
    if (fresh.length === 0) return;
    fresh.forEach((id) => seenRef.current.add(id));
    setNewIds(new Set(fresh));
    const t = setTimeout(() => setNewIds(new Set()), 2400);
    return () => clearTimeout(t);
  }, [data]);

  const facts = data?.facts ?? [];

  return (
    <div className="px-8 py-6">
      <header className="mb-6">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">Fact log</h1>
          <LiveDot />
        </div>
        <p className="text-xs text-[color:var(--color-fg-subtle)] mt-1">
          Every operational delta as it lands in the graph, newest first — one row per fact.
          {data ? ` ${data.count.toLocaleString()} facts.` : ""}
        </p>
      </header>

      {error && (
        <div className="text-sm text-[color:var(--color-status-cancelled)] mb-4">
          {(error as Error).message}
        </div>
      )}

      {isLoading && (
        <div className="text-sm text-[color:var(--color-fg-subtle)]">Loading…</div>
      )}

      {!isLoading && facts.length === 0 && (
        <div className="text-sm text-[color:var(--color-fg-subtle)]">
          No facts in the graph yet.
        </div>
      )}

      <ol className="space-y-2">
        {facts.map((f) => (
          <FactEntry key={f.edge_id} fact={f} isNew={newIds.has(f.edge_id)} />
        ))}
      </ol>
    </div>
  );
}

function FactEntry({ fact, isNew }: { fact: FactLogEntry; isNew: boolean }) {
  const accent = EDGE_COLOR[fact.edge_label] ?? "var(--color-fg-subtle)";
  return (
    <li
      className={`relative rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-surface)] pl-4 pr-4 py-3 overflow-hidden transition-[opacity,filter] duration-500 ${
        isNew ? "pearscarf-fact-enter" : ""
      } ${fact.stale ? "opacity-45 grayscale blur-[0.6px]" : ""}`}
    >
      {/* Edge-type accent bar */}
      <span
        className="absolute left-0 top-0 bottom-0 w-1"
        style={{ backgroundColor: accent }}
        aria-hidden="true"
      />

      <div className="flex items-center gap-2 mb-1.5">
        <span
          className="text-[10px] font-semibold uppercase tracking-wider"
          style={{ color: accent }}
        >
          {prettyEdge(fact.edge_label)}
        </span>
        {fact.fact_type && (
          <span className="text-[10px] font-mono text-[color:var(--color-fg-subtle)]">
            {fact.fact_type}
          </span>
        )}
        {fact.stale && (
          <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-[color:var(--color-status-cancelled)]/15 text-[color:var(--color-status-cancelled)]">
            stale
          </span>
        )}
        {isNew && (
          <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-[color:var(--color-accent)]/20 text-[color:var(--color-accent)] font-semibold">
            new
          </span>
        )}
        <span className="ml-auto text-[11px] text-[color:var(--color-fg-muted)] whitespace-nowrap">
          {fact.recorded_at
            ? relativeTime(fact.recorded_at)
            : fact.source_at
              ? relativeTime(fact.source_at)
              : "—"}
        </span>
      </div>

      <p className="text-sm leading-relaxed text-[color:var(--color-fg)]">
        {fact.fact || "(no fact text)"}
      </p>

      {/* subject → target — the structural relationship, surfaced as chips */}
      <div className="flex flex-wrap items-center gap-2 mt-2.5">
        {fact.subject_name && (
          <EntityChip label={displayLabel(fact.subject_labels)} name={fact.subject_name} />
        )}
        {fact.other_name && (
          <>
            <span
              className="text-base leading-none text-[color:var(--color-fg-muted)] font-semibold"
              aria-hidden="true"
            >
              →
            </span>
            <EntityChip label={displayLabel(fact.other_labels)} name={fact.other_name} />
          </>
        )}
        {fact.source_record && (
          <span className="ml-auto self-center text-[11px] font-mono text-[color:var(--color-fg-subtle)]">
            {fact.source_record}
          </span>
        )}
      </div>
    </li>
  );
}

const LABEL_COLOR: Record<string, string> = {
  Person: "var(--color-type-coordinator)",
  Company: "var(--color-type-executor)",
  Project: "var(--color-status-done)",
  Event: "var(--color-status-in-progress)",
};

function EntityChip({ label, name }: { label: string | null; name: string }) {
  const color = (label && LABEL_COLOR[label]) || "var(--color-fg-subtle)";
  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded border border-[color:var(--color-border)] bg-[color:var(--color-bg)] text-xs text-[color:var(--color-fg)]">
      <span
        className="inline-block w-2 h-2 rounded-full shrink-0"
        style={{ backgroundColor: color }}
        title={label ?? undefined}
        aria-hidden="true"
      />
      {name}
    </span>
  );
}
function LiveDot() {
  return (
    <span
      className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-[color:var(--color-status-done)]"
      title="Polling for new facts"
    >
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full rounded-full bg-[color:var(--color-status-done)] opacity-60 pearscarf-ping" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-[color:var(--color-status-done)]" />
      </span>
      live
    </span>
  );
}
