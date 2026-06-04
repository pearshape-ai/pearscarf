"use client";

import Link from "next/link";
import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { relativeTime, tokens } from "@/lib/format";
import { formatUsd } from "@/lib/pricing";

type Call = {
  id: number;
  created_at: string;
  runtime_id: string;
  consumer: string;
  agent_name: string;
  pearscarf_version: string;
  run_id: string;
  turn_index: number;
  provider: string;
  model: string;
  prompt_hash: string;
  prompt_body: string;
  stop_reason: string;
  tool_calls: unknown;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  latency_ms: number | null;
  record_id: string | null;
  session_id: string | null;
  error: string | null;
  input_messages: unknown;
  response_text: string | null;
  response_tool_calls: unknown;
  estimated_cost_usd: number;
};

async function fetchCall(id: string): Promise<Call> {
  const res = await fetch(`/api/llm-calls/${id}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export default function LlmCallDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, isLoading, error } = useQuery({
    queryKey: ["llm-call", id],
    queryFn: () => fetchCall(id),
  });

  if (isLoading) {
    return <div className="px-8 py-6 text-[color:var(--color-fg-subtle)]">Loading…</div>;
  }
  if (error || !data) {
    return (
      <div className="px-8 py-6 text-[color:var(--color-status-cancelled)] text-sm">
        {error ? (error as Error).message : "Not found"}
      </div>
    );
  }

  return (
    <div className="px-8 py-6">
      <Link
        href="/self-improvement"
        className="text-xs text-[color:var(--color-fg-subtle)] hover:text-[color:var(--color-fg-muted)]"
      >
        ← back to self-improvement
      </Link>
      <h1 className="text-lg font-semibold tracking-tight mt-2">
        Call #{data.id} · <span className="font-mono text-sm text-[color:var(--color-fg-muted)]">{data.model}</span>
      </h1>

      <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mt-4">
        <Stat label="Cost" value={formatUsd(data.estimated_cost_usd)} accent />
        <Stat label="Input" value={tokens(data.input_tokens)} />
        <Stat label="Output" value={tokens(data.output_tokens)} />
        <Stat label="Cache read" value={tokens(data.cache_read_tokens)} />
        <Stat label="Cache write" value={tokens(data.cache_creation_tokens)} />
        <Stat label="Latency" value={data.latency_ms ? `${data.latency_ms}ms` : "—"} />
      </div>

      <Section title="Metadata">
        <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
          <Field label="Consumer" value={data.consumer} />
          <Field label="Agent" value={data.agent_name} />
          <Field label="Provider" value={data.provider} mono />
          <Field label="Model" value={data.model} mono />
          <Field label="Run id" value={data.run_id} mono />
          <Field label="Turn" value={String(data.turn_index)} mono />
          <Field label="Pearscarf version" value={data.pearscarf_version} />
          <Field label="Stop reason" value={data.stop_reason} />
          <Field
            label="Record"
            value={
              data.record_id ? (
                <Link href={`/intents/${data.record_id}`} className="font-mono text-xs hover:underline">
                  {data.record_id}
                </Link>
              ) : (
                "—"
              )
            }
          />
          <Field label="Session" value={data.session_id ?? "—"} mono />
          <Field label="Created" value={`${relativeTime(data.created_at)} · ${data.created_at}`} />
          {data.error && (
            <div className="col-span-2">
              <div className="text-xs text-[color:var(--color-fg-subtle)]">Error</div>
              <pre className="mt-0.5 whitespace-pre-wrap text-xs font-mono text-[color:var(--color-status-cancelled)] bg-[color:var(--color-surface)] border border-[color:var(--color-status-cancelled)]/30 rounded p-3">
                {data.error}
              </pre>
            </div>
          )}
        </dl>
      </Section>

      <Section title="System prompt">
        <pre className="whitespace-pre-wrap text-xs font-mono bg-[color:var(--color-surface)] border border-[color:var(--color-border)] rounded p-4 max-h-96 overflow-auto">
          {data.prompt_body || "(empty)"}
        </pre>
      </Section>

      <Section title="Input messages (conversation)">
        <pre className="text-xs font-mono bg-[color:var(--color-surface)] border border-[color:var(--color-border)] rounded p-4 max-h-96 overflow-auto">
          {data.input_messages
            ? JSON.stringify(data.input_messages, null, 2)
            : "(not captured)"}
        </pre>
      </Section>

      <Section title="Response text">
        <pre className="whitespace-pre-wrap text-sm bg-[color:var(--color-surface)] border border-[color:var(--color-border)] rounded p-4 max-h-96 overflow-auto">
          {data.response_text || "(none — likely tool-only turn)"}
        </pre>
      </Section>

      <Section title="Response tool calls">
        <pre className="text-xs font-mono bg-[color:var(--color-surface)] border border-[color:var(--color-border)] rounded p-4 max-h-96 overflow-auto">
          {data.response_tool_calls
            ? JSON.stringify(data.response_tool_calls, null, 2)
            : "(none)"}
        </pre>
      </Section>
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
      <div className="text-base font-semibold tracking-tight mt-1">{value}</div>
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
