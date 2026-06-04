"use client";

import Link from "next/link";
import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { StatusBadge, TypeBadge } from "@/components/status-badge";
import { relativeTime, truncate } from "@/lib/format";
import { extractTitle } from "@/lib/title";

const POLL_MS = parseInt(process.env.NEXT_PUBLIC_POLL_INTERVAL_MS || "4000", 10);

type Intent = {
  id: string;
  created_at: string;
  set_at: string;
  set_by: string | null;
  source: string;
  status: string;
  intent_type: string;
  parent_record_id: string | null;
  owner: string | null;
  owner_role: string | null;
  runtime: string;
  runtime_config: Record<string, unknown>;
  depends_on: string[];
  body: string;
};

type Child = {
  id: string;
  status: string;
  intent_type: string;
  owner: string | null;
  owner_role: string | null;
  runtime: string;
  body: string;
  set_at: string;
};

async function fetchIntent(id: string): Promise<{ intent: Intent; children: Child[] }> {
  const res = await fetch(`/api/intents/${id}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export default function IntentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data, error, isLoading } = useQuery({
    queryKey: ["intent", id],
    queryFn: () => fetchIntent(id),
    refetchInterval: POLL_MS,
  });

  if (isLoading) {
    return <div className="px-8 py-6 text-[color:var(--color-fg-subtle)]">Loading…</div>;
  }
  if (error) {
    return (
      <div className="px-8 py-6 text-[color:var(--color-status-cancelled)] text-sm">
        {(error as Error).message}
      </div>
    );
  }
  if (!data) return null;
  const { intent, children } = data;

  return (
    <div className="px-8 py-6">
      <Link
        href="/intents"
        className="text-xs text-[color:var(--color-fg-subtle)] hover:text-[color:var(--color-fg-muted)]"
      >
        ← all intents
      </Link>
      <header className="mt-2 flex items-start gap-3 flex-wrap">
        <StatusBadge status={intent.status} />
        <TypeBadge type={intent.intent_type} />
        <span className="text-[10px] font-mono text-[color:var(--color-fg-subtle)] self-center">
          {intent.id}
        </span>
      </header>

      <h1 className="text-lg font-semibold tracking-tight mt-3 mb-4">
        {extractTitle(intent.body)}
      </h1>

      <Section title="Body">
        <pre className="whitespace-pre-wrap text-sm leading-relaxed font-sans text-[color:var(--color-fg)] bg-[color:var(--color-surface)] border border-[color:var(--color-border)] rounded p-4">
          {intent.body || "(empty)"}
        </pre>
      </Section>

      <Section title="Metadata">
        <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
          <Field label="Owner" value={intent.owner ?? "—"} />
          <Field label="Owner role" value={intent.owner_role ?? "—"} />
          <Field label="Runtime" value={intent.runtime} mono />
          <Field label="Source" value={intent.source || "—"} />
          <Field label="Created" value={`${relativeTime(intent.created_at)}  ·  ${intent.created_at}`} />
          <Field label="Last touched" value={`${relativeTime(intent.set_at)}  ·  ${intent.set_at} (by ${intent.set_by || "—"})`} />
          {intent.parent_record_id && (
            <Field
              label="Parent"
              value={
                <Link href={`/intents/${intent.parent_record_id}`} className="font-mono text-xs hover:underline">
                  {intent.parent_record_id}
                </Link>
              }
            />
          )}
          {intent.depends_on?.length > 0 && (
            <Field
              label="Depends on"
              value={intent.depends_on.map((d) => (
                <Link key={d} href={`/intents/${d}`} className="font-mono text-xs hover:underline mr-2">
                  {d}
                </Link>
              ))}
            />
          )}
        </dl>
      </Section>

      <Section title="Runtime config">
        <pre className="text-xs font-mono bg-[color:var(--color-surface)] border border-[color:var(--color-border)] rounded p-4 overflow-x-auto">
          {JSON.stringify(intent.runtime_config ?? {}, null, 2)}
        </pre>
      </Section>

      {children.length > 0 && (
        <Section title={`Children (${children.length})`}>
          <div className="border border-[color:var(--color-border)] rounded-md overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-[color:var(--color-surface)] text-[color:var(--color-fg-muted)] text-xs uppercase tracking-wide">
                <tr>
                  <th className="text-left px-4 py-2 font-medium w-24">Status</th>
                  <th className="text-left px-4 py-2 font-medium w-28">Type</th>
                  <th className="text-left px-4 py-2 font-medium">Title</th>
                  <th className="text-left px-4 py-2 font-medium w-44">Owner / role</th>
                  <th className="text-left px-4 py-2 font-medium w-24">Touched</th>
                </tr>
              </thead>
              <tbody>
                {children.map((c) => (
                  <tr
                    key={c.id}
                    className="border-t border-[color:var(--color-border)] hover:bg-[color:var(--color-surface-hover)]"
                  >
                    <td className="px-4 py-2.5">
                      <StatusBadge status={c.status} />
                    </td>
                    <td className="px-4 py-2.5">
                      <TypeBadge type={c.intent_type} />
                    </td>
                    <td className="px-4 py-2.5 max-w-xl">
                      <Link href={`/intents/${c.id}`} className="hover:underline font-medium">
                        {extractTitle(c.body)}
                      </Link>
                      <span className="block text-[10px] font-mono text-[color:var(--color-fg-subtle)] mt-0.5">
                        {c.id}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-[color:var(--color-fg-muted)]">
                      <div className="font-medium text-[color:var(--color-fg)]">{c.owner ?? "—"}</div>
                      <div className="text-xs">{c.owner_role ?? "—"}</div>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-[color:var(--color-fg-muted)]">{relativeTime(c.set_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <h2 className="text-xs font-medium uppercase tracking-wide text-[color:var(--color-fg-muted)] mb-2">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Field({
  label,
  value,
  mono,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-xs text-[color:var(--color-fg-subtle)]">{label}</dt>
      <dd className={`mt-0.5 ${mono ? "font-mono text-xs" : ""}`}>{value}</dd>
    </div>
  );
}
