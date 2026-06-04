/**
 * Tiny inline pill — color-coded by status. Server + client safe.
 */

const STATUS_STYLES: Record<string, string> = {
  todo: "bg-[color:var(--color-status-todo)]/15 text-[color:var(--color-status-todo)] ring-1 ring-inset ring-[color:var(--color-status-todo)]/30",
  in_progress: "bg-[color:var(--color-status-in-progress)]/15 text-[color:var(--color-status-in-progress)] ring-1 ring-inset ring-[color:var(--color-status-in-progress)]/30",
  done: "bg-[color:var(--color-status-done)]/15 text-[color:var(--color-status-done)] ring-1 ring-inset ring-[color:var(--color-status-done)]/30",
  cancelled: "bg-[color:var(--color-status-cancelled)]/15 text-[color:var(--color-status-cancelled)] ring-1 ring-inset ring-[color:var(--color-status-cancelled)]/30",
};

const TYPE_STYLES: Record<string, string> = {
  executor: "bg-[color:var(--color-type-executor)]/12 text-[color:var(--color-type-executor)] ring-1 ring-inset ring-[color:var(--color-type-executor)]/30",
  coordinator: "bg-[color:var(--color-type-coordinator)]/12 text-[color:var(--color-type-coordinator)] ring-1 ring-inset ring-[color:var(--color-type-coordinator)]/30",
};

export function StatusBadge({ status }: { status: string }) {
  const cls =
    STATUS_STYLES[status] ?? "bg-[color:var(--color-border-strong)] text-[color:var(--color-fg-muted)]";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function TypeBadge({ type }: { type: string }) {
  const cls =
    TYPE_STYLES[type] ?? "bg-[color:var(--color-border-strong)] text-[color:var(--color-fg-muted)]";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {type}
    </span>
  );
}
