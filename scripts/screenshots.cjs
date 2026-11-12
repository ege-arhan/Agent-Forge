// Captures the dashboard screenshots for docs/screenshots/.
// Started by scripts/screenshots.py, which seeds OFFLINE demo data and runs
// the API and the dashboard. Usage: node scripts/screenshots.cjs OUT_DIR
"use strict";

const path = require("node:path");
const { chromium } = require("playwright");

const API = process.env.AF_API || "http://127.0.0.1:8000";
const WEB = process.env.AF_WEB || "http://localhost:3000";
const APPROVAL_RUN = process.env.AF_APPROVAL_RUN || "";
const OUT = path.resolve(process.argv[2] || "docs/screenshots");

async function api(pathname) {
  const response = await fetch(`${API}/api/v1${pathname}`);
  if (!response.ok) throw new Error(`GET ${pathname}: ${response.status}`);
  return response.json();
}

function need(value, what) {
  if (!value) throw new Error(`demo data is missing ${what}`);
  return value;
}

async function targets() {
  const agents = await api("/agents");
  const demoCoder = need(agents.find((a) => a.name === "dogfood-demo-coder"), "the tour agent");
  const benches = await api("/benchmarks/runs?limit=200");
  const starter = need(benches.find((b) => b.suite_id === "starter"), "the starter benchmark");
  const experiments = await api("/experiments");
  const experiment = need(experiments[0], "an experiment");
  const runs = await api("/runs?limit=200");
  const fixRun = need(
    runs.items.find((r) => r.status === "succeeded" && /test_calc/.test(r.goal || "")),
    "a succeeded bug-fix run",
  );
  return [
    { file: "dashboard-light.png", url: "/", theme: "light" },
    { file: "runs-light.png", url: "/runs", theme: "light" },
    { file: "run-detail-dark.png", url: `/runs/${fixRun.id}`, theme: "dark" },
    { file: "run-approval-light.png", url: `/runs/${need(APPROVAL_RUN, "AF_APPROVAL_RUN")}`, theme: "light", wait: "Pending approval" },
    { file: "benchmark-detail-light.png", url: `/benchmarks/${starter.id}`, theme: "light" },
    { file: "experiment-light.png", url: `/experiments/${experiment.id}`, theme: "light" },
    { file: "improvement-agent-light.png", url: `/improvement/${demoCoder.id}`, theme: "light" },
    { file: "improvement-dark.png", url: "/improvement", theme: "dark" },
  ];
}

async function main() {
  const shots = await targets();
  const browser = await chromium.launch();
  try {
    for (const shot of shots) {
      const context = await browser.newContext({
        viewport: { width: 1440, height: 900 },
        deviceScaleFactor: 1,
        colorScheme: shot.theme,
      });
      await context.addInitScript((theme) => {
        localStorage.setItem("agentforge.theme", theme);
      }, shot.theme);
      const page = await context.newPage();
      await page.goto(`${WEB}${shot.url}`, { waitUntil: "load", timeout: 120000 });
      // Pages of live runs keep polling, so "idle" may never come; that is fine.
      await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
      if (shot.wait) await page.getByText(shot.wait).first().waitFor({ timeout: 30000 });
      // The Next.js dev-mode indicator is not part of the dashboard.
      await page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });
      await page.waitForTimeout(500);
      await page.screenshot({ path: path.join(OUT, shot.file), fullPage: true });
      console.log(`wrote ${shot.file}  (${shot.url})`);
      await context.close();
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(`screenshots failed: ${error.message}`);
  process.exit(1);
});
