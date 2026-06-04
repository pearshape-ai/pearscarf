"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { relativeTime } from "@/lib/format";

const POLL_MS = parseInt(process.env.NEXT_PUBLIC_POLL_INTERVAL_MS || "4000", 10);

type Entity = {
  id: string;
  label: string | null;
  name: string | null;
  created_at: string | null;
  fact_count: number;
  most_recent_source_at: string | null;
  aliases: string[];
};

type Stats = {
  totals: {
    entities: number;
    facts_total: number;
    facts_current: number;
    facts_stale: number;
  };
  by_label: { label: string; count: number }[];
  by_edge: { edge_label: string; total: number; current: number; stale: number }[];
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
  other_id: string | null;
  other_name: string | null;
  other_label: string | null;
};

const ENTITY_LABELS = ["Person", "Company", "Project", "Event"] as const;
type EntityLabel = (typeof ENTITY_LABELS)[number];

async function fetchStats(): Promise<Stats> {
  const res = await fetch("/api/graph/stats", { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function fetchEntities(label: EntityLabel | "all"): Promise<Entity[]> {
  const url = label === "all" ? "/api/graph/entities" : `/api/graph/entities?label=${label}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()).entities;
}

async function fetchFacts(id: string): Promise<{ entity: Entity; facts: Fact[] }> {
  const res = await fetch(`/api/graph/entities/${encodeURIComponent(id)}/facts`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export default function RealityPage() {
  const [filter, setFilter] = useState<EntityLabel | "all">("all");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const statsQ = useQuery({
    queryKey: ["graph-stats"],
    queryFn: fetchStats,
    refetchInterval: POLL_MS,
  });
  const entitiesQ = useQuery({
    queryKey: ["graph-entities", filter],
    queryFn: () => fetchEntities(filter),
    refetchInterval: POLL_MS,
  });

  return (
    <div className="px-8 py-6">
      <header className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight">Reality</h1>
        <p className="text-xs text-[color:var(--color-fg-subtle)] mt-1">
          What pearscarf knows is true right now — entities and the non-stale facts
          asserted about them.
          {entitiesQ.dataUpdatedAt
            ? ` Updated ${relativeTime(new Date(entitiesQ.dataUpdatedAt))}.`
            : ""}
        </p>
      </header>

      {statsQ.data && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-6">
          <Stat label="Entities" value={statsQ.data.totals.entities.toLocaleString()} accent />
          <Stat label="Current facts" value={statsQ.data.totals.facts_current.toLocaleString()} />
          <Stat label="Stale facts" value={statsQ.data.totals.facts_stale.toLocaleString()} />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="flex flex-wrap items-center gap-1.5">
          <FilterChip
            label="All"
            count={statsQ.data?.totals.entities}
            active={filter === "all"}
            onClick={() => setFilter("all")}
          />
          {ENTITY_LABELS.map((lbl) => (
            <FilterChip
              key={lbl}
              label={lbl}
              count={statsQ.data?.by_label.find((l) => l.label === lbl)?.count}
              active={filter === lbl}
              onClick={() => setFilter(lbl)}
            />
          ))}
        </div>
        <div className="flex-1 min-w-[200px] max-w-xs ml-auto relative">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search entities…"
            className="w-full bg-[color:var(--color-surface)] border border-[color:var(--color-border)] rounded px-2.5 py-1 text-xs text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-accent)]/60"
            aria-label="Search entities"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[color:var(--color-fg-subtle)] hover:text-[color:var(--color-fg)] text-xs px-1"
              aria-label="Clear search"
            >
              ×
            </button>
          )}
        </div>
      </div>

      {entitiesQ.error && (
        <div className="text-sm text-[color:var(--color-status-cancelled)] mb-4">
          {(entitiesQ.error as Error).message}
        </div>
      )}

      <div className="border border-[color:var(--color-border)] rounded-md overflow-hidden bg-[color:var(--color-surface)]">
        <table className="w-full text-sm">
          <thead className="bg-[color:var(--color-surface)] text-[color:var(--color-fg-muted)] text-xs uppercase tracking-wide">
            <tr>
              <th className="text-left px-4 py-2 font-medium w-8"></th>
              <th className="text-left px-4 py-2 font-medium w-24">Label</th>
              <th className="text-left px-4 py-2 font-medium">Name</th>
              <th className="text-right px-4 py-2 font-medium w-24">Facts</th>
              <th className="text-left px-4 py-2 font-medium w-32">Last touched</th>
            </tr>
          </thead>
          <tbody>
            {entitiesQ.isLoading && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-[color:var(--color-fg-subtle)]">
                  Loading…
                </td>
              </tr>
            )}
            {(() => {
              const all = entitiesQ.data ?? [];
              const needle = search.trim().toLowerCase();
              const visible = needle
                ? all.filter((e) => {
                    const name = (e.name ?? "").toLowerCase();
                    if (name.includes(needle)) return true;
                    return e.aliases.some((a) => a.toLowerCase().includes(needle));
                  })
                : all;

              if (visible.length === 0) {
                return (
                  <tr>
                    <td
                      colSpan={5}
                      className="px-4 py-8 text-center text-[color:var(--color-fg-subtle)]"
                    >
                      {needle
                        ? `No entities match "${search.trim()}".`
                        : "No entities match this filter."}
                    </td>
                  </tr>
                );
              }
              return visible.map((e) => (
                <EntityRow
                  key={e.id}
                  entity={e}
                  expanded={!!expanded[e.id]}
                  onToggle={() =>
                    setExpanded((s) => ({ ...s, [e.id]: !s[e.id] }))
                  }
                />
              ));
            })()}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EntityRow({
  entity,
  expanded,
  onToggle,
}: {
  entity: Entity;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr
        onClick={onToggle}
        className="border-t border-[color:var(--color-border)] hover:bg-[color:var(--color-surface-hover)] cursor-pointer"
      >
        <td className="px-4 py-2.5 text-[color:var(--color-fg-subtle)]">
          <span className={`inline-block transition-transform ${expanded ? "rotate-90" : ""}`}>
            ▸
          </span>
        </td>
        <td className="px-4 py-2.5">
          <LabelBadge label={entity.label} />
        </td>
        <td className="px-4 py-2.5">
          <span className="font-medium">{entity.name || "(unnamed)"}</span>
          {entity.aliases.length > 0 && (
            <span className="text-xs text-[color:var(--color-fg-subtle)] ml-2">
              (aka: {entity.aliases.join(", ")})
            </span>
          )}
        </td>
        <td className="px-4 py-2.5 text-right font-mono text-xs">
          {entity.fact_count}
        </td>
        <td className="px-4 py-2.5 text-xs text-[color:var(--color-fg-muted)]">
          {entity.most_recent_source_at ? relativeTime(entity.most_recent_source_at) : "—"}
        </td>
      </tr>
      {expanded && (
        <tr className="border-t border-[color:var(--color-border)] bg-[color:var(--color-bg)]">
          <td colSpan={5} className="px-8 py-4">
            <ExpandedFacts id={entity.id} />
          </td>
        </tr>
      )}
    </>
  );
}

function ExpandedFacts({ id }: { id: string }) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["graph-facts", id],
    queryFn: () => fetchFacts(id),
    refetchInterval: POLL_MS,
  });

  if (isLoading) {
    return <div className="text-xs text-[color:var(--color-fg-subtle)]">Loading facts…</div>;
  }
  if (error) {
    return (
      <div className="text-xs text-[color:var(--color-status-cancelled)]">
        {(error as Error).message}
      </div>
    );
  }
  if (!data) return null;
  if (data.facts.length === 0) {
    return (
      <div className="text-xs text-[color:var(--color-fg-subtle)]">
        No non-stale facts on this entity.
      </div>
    );
  }

  // Group by edge_label so the section reads as Affiliations / Assertions / Transitions.
  const byEdge: Record<string, Fact[]> = {};
  for (const f of data.facts) {
    (byEdge[f.edge_label] ||= []).push(f);
  }
  const ORDER = ["AFFILIATED", "ASSERTED", "TRANSITIONED"];
  const groups = Object.entries(byEdge).sort(
    ([a], [b]) => (ORDER.indexOf(a) + 100) - (ORDER.indexOf(b) + 100),
  );

  return (
    <div className="space-y-4">
      {groups.map(([edge, facts]) => (
        <div key={edge}>
          <h3 className="text-[10px] uppercase tracking-wider text-[color:var(--color-fg-subtle)] mb-2">
            {prettyEdge(edge)} ({facts.length})
          </h3>
          <ul className="divide-y divide-[color:var(--color-border)]/70">
            {facts.map((f) => (
              <FactRow key={f.edge_id} fact={f} />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function FactRow({ fact }: { fact: Fact }) {
  return (
    <li className="text-sm leading-relaxed py-2 first:pt-0 last:pb-0">
      <span>{fact.fact}</span>
      <span className="ml-2 text-[10px] font-mono text-[color:var(--color-fg-subtle)]">
        {fact.fact_type ? `[${fact.fact_type}]` : ""}
        {fact.confidence ? ` · ${fact.confidence}` : ""}
        {fact.source_at ? ` · ${relativeTime(fact.source_at)}` : ""}
        {fact.other_name ? ` · → ${fact.other_name}` : ""}
      </span>
    </li>
  );
}

function prettyEdge(edge: string): string {
  switch (edge) {
    case "AFFILIATED":
      return "Affiliations";
    case "ASSERTED":
      return "Assertions";
    case "TRANSITIONED":
      return "Transitions";
    default:
      return edge.toLowerCase().replace(/_/g, " ");
  }
}

function LabelBadge({ label }: { label: string | null }) {
  if (!label) return <span className="text-xs text-[color:var(--color-fg-subtle)]">—</span>;
  const palette: Record<string, string> = {
    Person: "bg-[color:var(--color-type-coordinator)]/12 text-[color:var(--color-type-coordinator)] ring-[color:var(--color-type-coordinator)]/30",
    Company: "bg-[color:var(--color-type-executor)]/12 text-[color:var(--color-type-executor)] ring-[color:var(--color-type-executor)]/30",
    Project: "bg-[color:var(--color-status-done)]/12 text-[color:var(--color-status-done)] ring-[color:var(--color-status-done)]/30",
    Event: "bg-[color:var(--color-status-in-progress)]/12 text-[color:var(--color-status-in-progress)] ring-[color:var(--color-status-in-progress)]/30",
  };
  const cls = palette[label] ?? "bg-[color:var(--color-border-strong)] text-[color:var(--color-fg-muted)]";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ring-1 ring-inset ${cls}`}>
      {label}
    </span>
  );
}

function FilterChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
        active
          ? "bg-[color:var(--color-surface-active)] text-[color:var(--color-fg)]"
          : "text-[color:var(--color-fg-muted)] hover:bg-[color:var(--color-surface-active)]/50 hover:text-[color:var(--color-fg)]"
      }`}
    >
      {label}
      {count != null && (
        <span className="ml-1 text-[color:var(--color-fg-subtle)] font-normal">
          ({count})
        </span>
      )}
    </button>
  );
}

function Stat({
  label,
  value,
  accent,
  small,
}: {
  label: string;
  value: string;
  accent?: boolean;
  small?: boolean;
}) {
  return (
    <div
      className={`border rounded-md px-4 py-3 ${
        accent
          ? "border-[color:var(--color-accent)]/40 bg-[color:var(--color-accent)]/10"
          : "border-[color:var(--color-border)] bg-[color:var(--color-surface)]"
      }`}
    >
      <div className="text-xs text-[color:var(--color-fg-subtle)]">{label}</div>
      <div className={`${small ? "text-xs text-[color:var(--color-fg-muted)]" : "text-lg font-semibold tracking-tight"} mt-1`}>
        {value}
      </div>
    </div>
  );
}
