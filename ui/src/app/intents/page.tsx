"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { StatusBadge, TypeBadge } from "@/components/status-badge";
import { relativeTime } from "@/lib/format";
import { extractTitle } from "@/lib/title";

const POLL_MS = parseInt(process.env.NEXT_PUBLIC_POLL_INTERVAL_MS || "4000", 10);
const VIEW_STORAGE_KEY = "pearscarf-ui:intents-view";

type View = "flat" | "nested";

type Intent = {
  id: string;
  created_at: string;
  set_at: string;
  set_by: string | null;
  status: string;
  intent_type: string;
  parent_record_id: string | null;
  owner: string | null;
  owner_role: string | null;
  runtime: string;
  body: string;
  child_total: number;
  child_done: number;
  child_in_flight: number;
};

async function fetchIntents(): Promise<Intent[]> {
  const res = await fetch("/api/intents", { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return data.intents;
}

export default function IntentsPage() {
  const [view, setView] = useState<View>("flat");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  // Restore view preference after mount.
  useEffect(() => {
    const stored = window.localStorage.getItem(VIEW_STORAGE_KEY);
    if (stored === "flat" || stored === "nested") setView(stored);
  }, []);

  function toggleView(next: View) {
    setView(next);
    window.localStorage.setItem(VIEW_STORAGE_KEY, next);
  }

  function toggleExpanded(id: string) {
    setExpanded((s) => ({ ...s, [id]: !s[id] }));
  }

  const { data, error, isLoading, dataUpdatedAt } = useQuery({
    queryKey: ["intents"],
    queryFn: fetchIntents,
    refetchInterval: POLL_MS,
  });

  // Index by parent for nested view — built once per data refresh.
  const byParent: Record<string, Intent[]> = {};
  const topLevel: Intent[] = [];
  for (const i of data ?? []) {
    if (i.parent_record_id) {
      (byParent[i.parent_record_id] ||= []).push(i);
    } else {
      topLevel.push(i);
    }
  }

  return (
    <div className="px-8 py-6">
      <header className="flex items-start justify-between mb-6 gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Intents</h1>
          <p className="text-xs text-[color:var(--color-fg-subtle)] mt-1">
            {data ? `${data.length} intents` : "loading…"}
            {dataUpdatedAt ? ` · updated ${relativeTime(new Date(dataUpdatedAt))}` : ""}
          </p>
        </div>
        <ViewToggle view={view} onSet={toggleView} />
      </header>

      {error && (
        <div className="text-sm text-[color:var(--color-status-cancelled)] mb-4">
          {(error as Error).message}
        </div>
      )}

      <div className="border border-[color:var(--color-border)] rounded-md overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[color:var(--color-surface)] text-[color:var(--color-fg-muted)] text-xs uppercase tracking-wide">
            <tr>
              <th className="text-left px-4 py-2 font-medium w-24">Status</th>
              <th className="text-left px-4 py-2 font-medium w-28">Type</th>
              <th className="text-left px-4 py-2 font-medium">Title</th>
              <th className="text-left px-4 py-2 font-medium w-44">Owner / role</th>
              <th className="text-left px-4 py-2 font-medium w-24">Runtime</th>
              <th className="text-left px-4 py-2 font-medium w-32">Last Updated</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-[color:var(--color-fg-subtle)]">
                  Loading…
                </td>
              </tr>
            )}
            {data && data.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-[color:var(--color-fg-subtle)]">
                  No intents yet.
                </td>
              </tr>
            )}
            {view === "flat" &&
              data?.map((i) => (
                <IntentRow
                  key={i.id}
                  intent={i}
                  depth={0}
                  nested={false}
                  byParent={byParent}
                  expanded={expanded}
                  onToggle={toggleExpanded}
                />
              ))}
            {view === "nested" &&
              topLevel.map((i) => (
                <IntentRow
                  key={i.id}
                  intent={i}
                  depth={0}
                  nested={true}
                  byParent={byParent}
                  expanded={expanded}
                  onToggle={toggleExpanded}
                />
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function IntentRow({
  intent,
  depth,
  nested,
  byParent,
  expanded,
  onToggle,
}: {
  intent: Intent;
  depth: number;
  nested: boolean;
  byParent: Record<string, Intent[]>;
  expanded: Record<string, boolean>;
  onToggle: (id: string) => void;
}) {
  const children = byParent[intent.id] ?? [];
  const hasChildren = children.length > 0;
  const isExpanded = !!expanded[intent.id];
  const indentPx = nested ? depth * 32 : 0;

  const rowClickable = nested && hasChildren;
  const isChild = nested && depth > 0;

  return (
    <>
      <tr
        className={`border-t border-[color:var(--color-border)] hover:bg-[color:var(--color-surface-hover)] ${
          isChild
            ? "bg-[color:var(--color-surface-active)]/50 pearscarf-fade-in"
            : "bg-[color:var(--color-surface)]"
        } ${rowClickable ? "cursor-pointer" : ""}`}
        onClick={(e) => {
          if (!rowClickable) return;
          // Don't expand when the click is on a real interactive element
          // (the title's <Link>, the chevron <button>) — those keep their
          // own behavior.
          if (
            e.target instanceof HTMLElement &&
            e.target.closest("a, button")
          )
            return;
          onToggle(intent.id);
        }}
      >
        <td className="px-4 py-2.5">
          <StatusBadge status={intent.status} />
        </td>
        <td className="px-4 py-2.5">
          <TypeBadge type={intent.intent_type} />
        </td>
        <td className="px-4 py-2.5 max-w-xl">
          {/* Always reserve the chevron slot — even in flat view + nested-no-children
              — so the title's horizontal position stays stable across the toggle. */}
          <div className="flex items-center gap-1.5" style={{ paddingLeft: indentPx }}>
            {nested && hasChildren ? (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onToggle(intent.id);
                }}
                aria-label={isExpanded ? "Collapse children" : "Expand children"}
                className="w-4 h-4 inline-flex items-center justify-center shrink-0 text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-fg)]"
              >
                <span
                  className={`inline-block transition-transform text-sm leading-none font-semibold ${
                    isExpanded ? "rotate-90" : ""
                  }`}
                >
                  ▸
                </span>
              </button>
            ) : (
              <span className="w-4 h-4 inline-flex shrink-0" aria-hidden="true" />
            )}
            <Link
              href={`/intents/${intent.id}`}
              className="hover:underline font-medium truncate"
            >
              {extractTitle(intent.body)}
            </Link>
            {(intent.intent_type === "coordinator" || intent.child_total > 0) && (
              <ProgressPill done={intent.child_done} total={intent.child_total} inFlight={intent.child_in_flight} />
            )}
          </div>
          <span
            className="block text-[10px] font-mono text-[color:var(--color-fg-subtle)] mt-0.5"
            style={{ paddingLeft: indentPx + 22 }}
          >
            {intent.id}
          </span>
        </td>
        <td className="px-4 py-2.5 text-[color:var(--color-fg-muted)]">
          <div className="font-medium text-[color:var(--color-fg)]">
            {intent.owner ?? "—"}
          </div>
          <div className="text-xs">{intent.owner_role ?? "—"}</div>
        </td>
        <td className="px-4 py-2.5 text-[color:var(--color-fg-muted)] font-mono text-xs">
          {intent.runtime}
        </td>
        <td className="px-4 py-2.5 text-xs text-[color:var(--color-fg-muted)]">
          <div>{relativeTime(intent.set_at)}</div>
          {intent.set_by && (
            <div className="text-[10px] text-[color:var(--color-fg-subtle)] mt-0.5">
              by {intent.set_by}
            </div>
          )}
        </td>
      </tr>
      {nested &&
        hasChildren &&
        isExpanded &&
        children.map((c) => (
          <IntentRow
            key={c.id}
            intent={c}
            depth={depth + 1}
            nested
            byParent={byParent}
            expanded={expanded}
            onToggle={onToggle}
          />
        ))}
    </>
  );
}

/** Done-out-of-total pill for coordinator intents. White inside, colored
 * border. Border tints green when complete, amber while in flight, neutral
 * before any progress. */
function ProgressPill({
  done,
  total,
  inFlight,
}: {
  done: number;
  total: number;
  inFlight: number;
}) {
  if (total === 0) return null;
  const complete = done === total;
  const tone = complete
    ? "ring-[color:var(--color-status-done)]/70 text-[color:var(--color-status-done)]"
    : inFlight > 0
    ? "ring-[color:var(--color-status-in-progress)]/70 text-[color:var(--color-status-in-progress)]"
    : "ring-[color:var(--color-border-strong)] text-[color:var(--color-fg-muted)]";
  return (
    <span
      title={
        inFlight > 0
          ? `${done} of ${total} done · ${inFlight} in flight`
          : `${done} of ${total} done`
      }
      className={`inline-flex items-center px-2 py-0 rounded-full text-[10px] font-mono bg-[color:var(--color-surface)] ring-1 ring-inset ${tone} shrink-0`}
    >
      {done}/{total}
    </span>
  );
}

function ViewToggle({ view, onSet }: { view: View; onSet: (v: View) => void }) {
  return (
    <div className="inline-flex rounded border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-0.5 text-xs">
      <ToggleButton label="Flat" active={view === "flat"} onClick={() => onSet("flat")} />
      <ToggleButton label="Nested" active={view === "nested"} onClick={() => onSet("nested")} />
    </div>
  );
}

function ToggleButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-1 rounded font-medium transition-colors ${
        active
          ? "bg-[color:var(--color-surface-active)] text-[color:var(--color-fg)]"
          : "text-[color:var(--color-fg-muted)] hover:bg-[color:var(--color-surface-active)]/50 hover:text-[color:var(--color-fg)]"
      }`}
    >
      {label}
    </button>
  );
}
