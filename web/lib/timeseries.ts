// Pure helpers for the dashboard's per-day charts (unit-tested in timeseries.test.ts).

import type { DailyPoint } from "./types";

export interface Scale {
  max: number;
  ticks: number[];
}

/**
 * A y-axis from zero to a round number at or above `value`, in one to three
 * equal steps of 1, 2 or 5 × 10ⁿ. With `integer`, steps are whole numbers
 * (counts are never drawn against a 0.5 gridline).
 */
export function niceScale(value: number, integer = false): Scale {
  if (!Number.isFinite(value) || value <= 0) {
    return integer ? { max: 1, ticks: [0, 1] } : { max: 1, ticks: [0, 0.5, 1] };
  }
  const rough = value / 3;
  const power = 10 ** Math.floor(Math.log10(rough));
  const fraction = rough / power;
  let step = (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * power;
  if (integer) step = Math.max(1, Math.round(step));
  const count = Math.max(1, Math.ceil(value / step - 1e-9));
  // Multiply rather than add so 0.1 + 0.2 never shows up as a tick.
  const ticks = Array.from({ length: count + 1 }, (_, i) => Number((i * step).toPrecision(12)));
  return { max: count * step === 0 ? 1 : Number((count * step).toPrecision(12)), ticks };
}

/** Bar height as a percentage of the plot, clamped; null (unknown) and zero draw nothing. */
export function barHeight(value: number | null, max: number): number {
  if (value === null || !Number.isFinite(value) || value <= 0 || max <= 0) return 0;
  return Math.min(100, (value / max) * 100);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-03-08" → "8 Mar". Parsed as text: the API's days are UTC calendar days. */
export function formatDay(date: string): string {
  const [, month = 0, day = 0] = date.split("-").map(Number);
  return `${day} ${MONTHS[month - 1] ?? "?"}`;
}

/** Indexes of the days labelled under the x-axis: first, last and evenly spaced between. */
export function labelIndexes(count: number, labels = 4): number[] {
  if (count <= 0) return [];
  if (count <= labels) return Array.from({ length: count }, (_, i) => i);
  const picked = new Set<number>();
  for (let i = 0; i < labels; i += 1) picked.add(Math.round((i * (count - 1)) / (labels - 1)));
  return [...picked].sort((a, b) => a - b);
}

export interface RangeTotals {
  runs: number;
  succeeded: number;
  failed: number;
  tokens: number;
  /** null when no run in the range has known pricing — never zero for "unknown". */
  knownCostUsd: number | null;
  runsWithUnknownCost: number;
  /** Mean over all timed runs in the range (weighted by runs, not by day). */
  meanDurationSeconds: number | null;
}

export function rangeTotals(series: DailyPoint[]): RangeTotals {
  let cost: number | null = null;
  let duration = 0;
  let timed = 0;
  const totals = { runs: 0, succeeded: 0, failed: 0, tokens: 0, runsWithUnknownCost: 0 };
  for (const day of series) {
    totals.runs += day.runs;
    totals.succeeded += day.succeeded;
    totals.failed += day.failed;
    totals.tokens += day.input_tokens + day.output_tokens;
    totals.runsWithUnknownCost += day.runs_with_unknown_cost;
    if (day.known_cost_usd !== null) cost = (cost ?? 0) + day.known_cost_usd;
    if (day.mean_duration_seconds !== null && day.timed_runs > 0) {
      duration += day.mean_duration_seconds * day.timed_runs;
      timed += day.timed_runs;
    }
  }
  return {
    ...totals,
    knownCostUsd: cost,
    meanDurationSeconds: timed ? duration / timed : null,
  };
}

export interface AxisUnit {
  /** Seconds per axis unit. */
  seconds: number;
  suffix: string;
}

/** Seconds, minutes or hours for a duration axis, so its ticks stay short ("2m", not "1m 40s"). */
export function durationUnit(peakSeconds: number): AxisUnit {
  if (peakSeconds >= 2 * 3600) return { seconds: 3600, suffix: "h" };
  if (peakSeconds >= 2 * 60) return { seconds: 60, suffix: "m" };
  return { seconds: 1, suffix: "s" };
}
