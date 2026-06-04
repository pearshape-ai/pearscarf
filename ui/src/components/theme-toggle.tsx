"use client";

/**
 * Theme toggle — flips `data-theme` on <html> and persists in localStorage.
 * The pre-paint script in <head> reads the same key + falls back to
 * `prefers-color-scheme`, so we avoid a flash on initial load.
 */

import { useEffect, useState } from "react";

const STORAGE_KEY = "pearscarf-ui:theme";

type Theme = "light" | "dark";

function readInitial(): Theme {
  if (typeof window === "undefined") return "light";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");
  const [mounted, setMounted] = useState(false);

  // Sync with whatever the pre-paint script already applied.
  useEffect(() => {
    setTheme(readInitial());
    setMounted(true);
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    window.localStorage.setItem(STORAGE_KEY, next);
  }

  // Render a placeholder until we know which theme is active — prevents the
  // icon from briefly mismatching the actual theme.
  if (!mounted) {
    return (
      <button
        aria-label="Toggle theme"
        className="flex items-center gap-2.5 px-2.5 py-1.5 rounded text-sm text-[color:var(--color-fg-muted)] whitespace-nowrap"
      >
        <span className="w-4 h-4 inline-block shrink-0" />
        <span className="pearscarf-nav-label">Theme</span>
      </button>
    );
  }

  return (
    <button
      onClick={toggle}
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
      title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
      className="flex items-center gap-2.5 px-2.5 py-1.5 rounded text-sm text-[color:var(--color-fg-muted)] hover:bg-[color:var(--color-surface-hover)] hover:text-[color:var(--color-fg)] transition-colors whitespace-nowrap"
    >
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
      <span className="pearscarf-nav-label">{theme === "dark" ? "Light theme" : "Dark theme"}</span>
    </button>
  );
}

function SunIcon() {
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
    >
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  );
}

function MoonIcon() {
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
    >
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}
