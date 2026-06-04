"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import ThemeToggle from "./theme-toggle";

const ITEMS = [
  { href: "/intents", label: "Intents", icon: IntentsIcon },
  { href: "/reality", label: "Reality", icon: GraphIcon },
  { href: "/fact-log", label: "Fact log", icon: FactLogIcon },
  { href: "/self-improvement", label: "Self-improvement", icon: SelfImprovementIcon },
] as const;

const STORAGE_KEY = "pearscarf-ui:nav-collapsed";

export default function Nav() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mounted, setMounted] = useState(false);

  // Sync with whatever the pre-paint script applied (no flash).
  useEffect(() => {
    setCollapsed(window.localStorage.getItem(STORAGE_KEY) === "true");
    setMounted(true);
  }, []);

  function toggleCollapsed() {
    const next = !collapsed;
    setCollapsed(next);
    if (next) {
      document.documentElement.setAttribute("data-nav-collapsed", "true");
      window.localStorage.setItem(STORAGE_KEY, "true");
    } else {
      document.documentElement.removeAttribute("data-nav-collapsed");
      window.localStorage.setItem(STORAGE_KEY, "false");
    }
  }

  return (
    <nav className="pearscarf-nav flex flex-col border-r border-[color:var(--color-border)] bg-[color:var(--color-surface)] h-screen sticky top-0 overflow-hidden">
      <div className="px-4 py-5 text-sm font-semibold tracking-tight border-b border-[color:var(--color-border)] whitespace-nowrap">
        <span className="pearscarf-nav-brand-full">PearScarf</span>
        <span className="pearscarf-nav-brand-compact text-center block">P</span>
      </div>
      <ul className="flex flex-col gap-0.5 p-2 flex-1">
        {ITEMS.map((it) => {
          const active = pathname === it.href || pathname.startsWith(it.href + "/");
          const Icon = it.icon;
          return (
            <li key={it.href}>
              <Link
                href={it.href}
                title={it.label}
                className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded text-sm transition-colors whitespace-nowrap ${
                  active
                    ? "bg-[color:var(--color-surface-active)] text-[color:var(--color-fg)] font-medium"
                    : "text-[color:var(--color-fg-muted)] hover:bg-[color:var(--color-surface-hover)] hover:text-[color:var(--color-fg)]"
                }`}
              >
                <Icon />
                <span className="pearscarf-nav-label">{it.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
      <div className="border-t border-[color:var(--color-border)] p-2 flex flex-col gap-0.5">
        <ThemeToggle />
        <button
          onClick={toggleCollapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="flex items-center gap-2.5 px-2.5 py-1.5 rounded text-sm text-[color:var(--color-fg-muted)] hover:bg-[color:var(--color-surface-hover)] hover:text-[color:var(--color-fg)] transition-colors whitespace-nowrap"
        >
          {/* Pre-mount we don't know the state — render an icon that's symmetric.
              After mount, swap to a directional chevron. */}
          {mounted ? collapsed ? <ChevronRightIcon /> : <ChevronLeftIcon /> : <ChevronLeftIcon />}
          <span className="pearscarf-nav-label">{collapsed ? "Expand" : "Collapse"}</span>
        </button>
      </div>
    </nav>
  );
}

function IntentsIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="shrink-0"
    >
      <circle cx="5" cy="6" r="1.5" />
      <line x1="10" y1="6" x2="20" y2="6" />
      <circle cx="5" cy="12" r="1.5" />
      <line x1="10" y1="12" x2="20" y2="12" />
      <circle cx="5" cy="18" r="1.5" />
      <line x1="10" y1="18" x2="20" y2="18" />
    </svg>
  );
}

function GraphIcon() {
  // Three nodes + connecting edges — node-link diagram motif.
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="shrink-0"
    >
      <circle cx="6" cy="6" r="2.5" />
      <circle cx="18" cy="6" r="2.5" />
      <circle cx="12" cy="18" r="2.5" />
      <line x1="7.5" y1="7.5" x2="11" y2="16" />
      <line x1="16.5" y1="7.5" x2="13" y2="16" />
      <line x1="8.5" y1="6" x2="15.5" y2="6" />
    </svg>
  );
}

function FactLogIcon() {
  // Activity / pulse line — facts streaming into the graph live.
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="shrink-0"
    >
      <polyline points="2 12 7 12 10 5 14 19 17 12 22 12" />
    </svg>
  );
}

function SelfImprovementIcon() {
  // Spiral / loop motif — the self-improvement cycle: extract → curate → reuse.
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="shrink-0"
    >
      <path d="M21 12a9 9 0 1 1-3.5-7.1" />
      <polyline points="21 4 21 9 16 9" />
    </svg>
  );
}

function ChevronLeftIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="shrink-0"
    >
      <polyline points="15 18 9 12 15 6" />
    </svg>
  );
}

function ChevronRightIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="shrink-0"
    >
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}
