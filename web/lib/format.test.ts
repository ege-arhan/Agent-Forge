import assert from "node:assert/strict";
import { test } from "node:test";

import {
  barWidth,
  formatCost,
  formatDelta,
  formatDuration,
  formatPercent,
  formatTokens,
  isTerminal,
  relativeTime,
  truncate,
} from "./format.ts";

test("percent handles null and rounding", () => {
  assert.equal(formatPercent(null), "—");
  assert.equal(formatPercent(0.875), "88%");
  assert.equal(formatPercent(0.875, 1), "87.5%");
});

test("cost is never shown as zero when unknown", () => {
  assert.equal(formatCost(null), "unknown");
  assert.equal(formatCost(undefined), "unknown");
  assert.equal(formatCost(0), "$0");
  assert.equal(formatCost(0.0042), "$0.0042");
  assert.equal(formatCost(1.234), "$1.23");
});

test("durations", () => {
  assert.equal(formatDuration(0.25), "250 ms");
  assert.equal(formatDuration(12.34), "12.3 s");
  assert.equal(formatDuration(125), "2m 5s");
  assert.equal(formatDuration(3 * 3600 + 120), "3h 2m");
  assert.equal(formatDuration(null), "—");
});

test("tokens", () => {
  assert.equal(formatTokens(999), "999");
  assert.equal(formatTokens(12_345), "12.3k");
  assert.equal(formatTokens(2_500_000), "2.50M");
});

test("delta in percentage points", () => {
  assert.equal(formatDelta(0), "±0 pp");
  assert.equal(formatDelta(0.125), "+12.5 pp");
  assert.equal(formatDelta(-0.5), "−50 pp");
  assert.equal(formatDelta(null), "—");
});

test("relative time", () => {
  const now = new Date("2026-01-01T12:00:00Z");
  assert.equal(relativeTime("2026-01-01T11:59:58Z", now), "just now");
  assert.equal(relativeTime("2026-01-01T11:59:00Z", now), "1m ago");
  assert.equal(relativeTime("2026-01-01T09:00:00Z", now), "3h ago");
  assert.equal(relativeTime("2025-12-01T09:00:00Z", now), "2025-12-01");
});

test("bar width clamps", () => {
  assert.equal(barWidth(-1), 0);
  assert.equal(barWidth(0.5), 50);
  assert.equal(barWidth(2), 100);
  assert.equal(barWidth(null), 0);
});

test("misc", () => {
  assert.equal(truncate("abcdef", 4), "abc…");
  assert.equal(truncate("abc", 4), "abc");
  assert.ok(isTerminal("timed_out"));
  assert.ok(!isTerminal("running"));
});
