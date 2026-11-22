import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  // Next.js 16.4 writes AGENTS.md and CLAUDE.md into the project on every
  // `next dev`/`next build`. This repository keeps its agent instructions in
  // the root CLAUDE.md, so the generated files are turned off.
  agentRules: false,
};

export default nextConfig;
