// Records a short dashboard walk-through of the offline tour's data.
// Started by `scripts/screenshots.py --record`, which seeds OFFLINE demo data,
// runs the API and the dashboard and converts the video to a GIF.
// Usage: node scripts/recording.cjs OUT_DIR   (writes OUT_DIR/tour.webm)
// Prints one JSON line: {"video": "...", "trim_seconds": N}.
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const WEB = process.env.AF_WEB || "http://localhost:3000";
const APPROVAL_RUN = process.env.AF_APPROVAL_RUN || "";
const OUT = path.resolve(process.argv[2] || ".");
const SIZE = { width: 1280, height: 720 };
const TOUR_AGENT = "dogfood-demo-coder";

// Headless Chromium draws no pointer, so the recording shows its own.
const POINTER = `
  window.addEventListener("DOMContentLoaded", () => {
    const dot = document.createElement("div");
    dot.style.cssText =
      "position:fixed;z-index:2147483647;width:14px;height:14px;margin:-7px 0 0 -7px;" +
      "border-radius:50%;background:rgba(42,120,214,.55);border:1.5px solid #fff;" +
      "box-shadow:0 0 0 1px rgba(11,11,11,.35);pointer-events:none;left:-40px;top:-40px";
    document.documentElement.appendChild(dot);
    window.addEventListener("mousemove", (e) => {
      dot.style.left = e.clientX + "px";
      dot.style.top = e.clientY + "px";
    }, true);
  });
`;

async function settle(page, ms) {
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(ms);
}

async function pointAndClick(page, locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error("walk-through target is not visible");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 20 });
  await page.waitForTimeout(350);
  await locator.click();
}

async function scrollBy(page, pixels) {
  await page.evaluate((top) => window.scrollBy({ top, behavior: "smooth" }), pixels);
  await page.waitForTimeout(1400);
}

async function main() {
  if (!APPROVAL_RUN) throw new Error("demo data is missing AF_APPROVAL_RUN");
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const started = Date.now();
  const context = await browser.newContext({
    viewport: SIZE,
    deviceScaleFactor: 1,
    colorScheme: "light",
    recordVideo: { dir: OUT, size: SIZE },
  });
  let video;
  try {
    await context.addInitScript(() => localStorage.setItem("agentforge.theme", "light"));
    await context.addInitScript(POINTER);
    const page = await context.newPage();
    video = page.video();
    // Warm every route first so dev-mode compilation is not part of the recording.
    for (const url of ["/improvement", "/runs", `/runs/${APPROVAL_RUN}`, "/"]) {
      await page.goto(`${WEB}${url}`, { waitUntil: "load", timeout: 120000 });
      await settle(page, 300);
    }
    await page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });
    await page.getByText("API connected").waitFor({ timeout: 30000 });
    const trimSeconds = (Date.now() - started) / 1000;

    // 1. Overview.
    await page.waitForTimeout(1800);
    // 2. Improvement overview, then the tour agent's page with its cycle.
    await pointAndClick(page, page.getByRole("link", { name: "Improvement", exact: true }));
    await page.getByRole("link", { name: TOUR_AGENT }).first().waitFor({ timeout: 30000 });
    await settle(page, 1500);
    await pointAndClick(page, page.getByRole("link", { name: TOUR_AGENT }).first());
    await page.getByText("Failure analysis").first().waitFor({ timeout: 30000 });
    await settle(page, 1500);
    await scrollBy(page, 520);
    await page.waitForTimeout(1200);
    await scrollBy(page, 520);
    await page.waitForTimeout(1800);
    // 3. The run that waits for a human decision: approve it and watch it finish.
    await pointAndClick(page, page.getByRole("link", { name: "Runs", exact: true }));
    const row = page.locator(`a[href="/runs/${APPROVAL_RUN}"]`).first();
    await row.waitFor({ timeout: 30000 });
    await settle(page, 1200);
    await pointAndClick(page, row);
    await page.getByText("Pending approval").first().waitFor({ timeout: 30000 });
    await page.waitForTimeout(2000);
    await pointAndClick(page, page.getByRole("button", { name: "Approve" }));
    await page.getByText("Succeeded").first().waitFor({ timeout: 30000 });
    await page.waitForTimeout(2500);

    await context.close();
    const target = path.join(OUT, "tour.webm");
    fs.renameSync(await video.path(), target);
    console.log(JSON.stringify({ video: target, trim_seconds: Number(trimSeconds.toFixed(2)) }));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(`recording failed: ${error.message}`);
  process.exit(1);
});
