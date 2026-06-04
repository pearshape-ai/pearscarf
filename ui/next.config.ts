import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone", // smaller docker image
  experimental: {
    serverActions: { bodySizeLimit: "2mb" },
  },
  // Routes were renamed (/graph → /reality, /llm-calls → /self-improvement).
  // Redirect the old paths so stale bookmarks/links don't 404.
  async redirects() {
    return [
      { source: "/graph", destination: "/reality", permanent: true },
      { source: "/llm-calls", destination: "/self-improvement", permanent: true },
      { source: "/llm-calls/:id", destination: "/self-improvement/:id", permanent: true },
    ];
  },
};

export default config;
