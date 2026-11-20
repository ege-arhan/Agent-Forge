import assert from "node:assert/strict";
import { test } from "node:test";

import { barHeight, durationUnit, formatDay, labelIndexes, niceScale, rangeTotals } from "./timeseries.ts";
import type { DailyPoint } from "./types.ts";

function day(overrides: Partial<DailyPoint>): DailyPoint {
  return {
    date: "2026-03-08",
    runs: 0,
    succeeded: 0,
    failed: 0,
    evaluated: 0,
    passed: 0,
    input_tokens: 0,
    output_tokens: 0,
    known_cost_usd: null,
    runs_with_unknown_cost: 0,
    mean_duration_seconds: null,
    timed_runs: 0,
    ...overrides,
  };
}

test("niceScale picks round steps that cover the value", () => {
  assert.deepEqual(niceScale(7), { max: 10, ticks: [0, 5, 10] });
  assert.deepEqual(niceScale(100), { max: 100, ticks: [0, 50, 100] });
  assert.deepEqual(niceScale(1234), { max: 1500, ticks: [0, 500, 1000, 1500] });
  assert.deepEqual(niceScale(0.25), { max: 0.3, ticks: [0, 0.1, 0.2, 0.3] });
  for (const value of [0.003, 0.9, 1, 3, 11, 47, 999, 123456]) {
    const scale = niceScale(value);
    assert.ok(scale.max >= value, `${value} fits under ${scale.max}`);
    assert.ok(scale.ticks.length >= 2 && scale.ticks.length <= 4, `${value}: ${scale.ticks}`);
  }
});

test("niceScale keeps whole-number ticks for counts", () => {
  assert.deepEqual(niceScale(1, true), { max: 1, ticks: [0, 1] });
  assert.deepEqual(niceScale(2, true), { max: 2, ticks: [0, 1, 2] });
  assert.deepEqual(niceScale(3, true), { max: 3, ticks: [0, 1, 2, 3] });
  for (const value of [1, 2, 3, 4, 5, 9, 17, 250]) {
    assert.ok(niceScale(value, true).ticks.every(Number.isInteger), String(value));
  }
});

test("niceScale has a usable axis when there is nothing to plot", () => {
  assert.deepEqual(niceScale(0, true), { max: 1, ticks: [0, 1] });
  assert.deepEqual(niceScale(Number.NaN), { max: 1, ticks: [0, 0.5, 1] });
});

test("barHeight draws nothing for unknown or zero and clamps", () => {
  assert.equal(barHeight(null, 10), 0);
  assert.equal(barHeight(0, 10), 0);
  assert.equal(barHeight(5, 10), 50);
  assert.equal(barHeight(20, 10), 100);
  assert.equal(barHeight(5, 0), 0);
});

test("formatDay reads the date as text, not in the local timezone", () => {
  assert.equal(formatDay("2026-03-08"), "8 Mar");
  assert.equal(formatDay("2026-12-31"), "31 Dec");
  assert.equal(formatDay("2026-01-01"), "1 Jan");
});

test("labelIndexes always includes both ends", () => {
  assert.deepEqual(labelIndexes(0), []);
  assert.deepEqual(labelIndexes(1), [0]);
  assert.deepEqual(labelIndexes(3), [0, 1, 2]);
  assert.deepEqual(labelIndexes(7), [0, 2, 4, 6]);
  assert.deepEqual(labelIndexes(30), [0, 10, 19, 29]);
});

test("rangeTotals keeps unknown cost unknown and weights duration by runs", () => {
  const empty = rangeTotals([day({}), day({ runs: 1, runs_with_unknown_cost: 1 })]);
  assert.equal(empty.knownCostUsd, null);
  assert.equal(empty.runsWithUnknownCost, 1);
  assert.equal(empty.meanDurationSeconds, null);

  const totals = rangeTotals([
    day({
      runs: 3,
      succeeded: 2,
      failed: 1,
      input_tokens: 100,
      output_tokens: 10,
      known_cost_usd: 0.5,
      mean_duration_seconds: 10,
      timed_runs: 3,
    }),
    day({ runs: 1, succeeded: 1, input_tokens: 5, known_cost_usd: 0, mean_duration_seconds: 50, timed_runs: 1 }),
    day({}),
  ]);
  assert.equal(totals.runs, 4);
  assert.equal(totals.succeeded, 3);
  assert.equal(totals.failed, 1);
  assert.equal(totals.tokens, 115);
  assert.equal(totals.knownCostUsd, 0.5);
  assert.equal(totals.meanDurationSeconds, 20);
});

test("durationUnit keeps duration ticks in one short unit", () => {
  assert.deepEqual(durationUnit(0), { seconds: 1, suffix: "s" });
  assert.deepEqual(durationUnit(119), { seconds: 1, suffix: "s" });
  assert.deepEqual(durationUnit(120), { seconds: 60, suffix: "m" });
  assert.deepEqual(durationUnit(7199), { seconds: 60, suffix: "m" });
  assert.deepEqual(durationUnit(7200), { seconds: 3600, suffix: "h" });
});
