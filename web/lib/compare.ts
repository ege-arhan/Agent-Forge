// Pure helpers for the run comparison view (unit-tested in compare.test.ts).
//
// Two runs are compared as recorded: metrics, evaluator results, the
// configuration snapshots and the tool calls step by step. Nothing here is a
// statistic - one run each says what happened, not how often it happens.

import type { EvaluationResult, Run, Step, ToolCallStatus } from "./types.ts";

export const MAX_COMPARED = 2;

/** Keep at most `max` selected ids; selecting one more drops the oldest. */
export function toggleSelection(selected: string[], id: string, max = MAX_COMPARED): string[] {
  if (selected.includes(id)) return selected.filter((s) => s !== id);
  return [...selected, id].slice(-max);
}

export function compareHref(a: string, b: string): string {
  return `/runs/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`;
}

export type MetricKind = "duration" | "count" | "tokens" | "percent" | "score" | "cost";

export interface MetricRow {
  key: string;
  label: string;
  kind: MetricKind;
  a: number | null;
  b: number | null;
  /** `b - a`; null when either side is unknown (never treated as zero). */
  delta: number | null;
}

function metric(key: string, label: string, kind: MetricKind, a: number | null, b: number | null): MetricRow {
  return { key, label, kind, a, b, delta: a === null || b === null ? null : b - a };
}

export function metricRows(a: Run, b: Run): MetricRow[] {
  const ma = a.metrics;
  const mb = b.metrics;
  return [
    metric("score", "Evaluation score", "score", a.evaluation?.score ?? null, b.evaluation?.score ?? null),
    metric("duration", "Duration", "duration", ma.duration_seconds, mb.duration_seconds),
    metric("steps", "Steps", "count", ma.steps, mb.steps),
    metric("tool_calls", "Tool calls", "count", ma.tool_calls, mb.tool_calls),
    metric("tool_errors", "Tool errors", "count", ma.tool_errors, mb.tool_errors),
    metric("tool_success_rate", "Tool success rate", "percent", ma.tool_success_rate, mb.tool_success_rate),
    metric("llm_calls", "LLM calls", "count", ma.llm_calls, mb.llm_calls),
    metric("llm_retries", "LLM retries", "count", ma.llm_retries, mb.llm_retries),
    metric("input_tokens", "Input tokens", "tokens", ma.input_tokens, mb.input_tokens),
    metric("output_tokens", "Output tokens", "tokens", ma.output_tokens, mb.output_tokens),
    metric("cost", "Estimated cost", "cost", ma.cost_usd, mb.cost_usd),
  ];
}

export interface CheckRow {
  name: string;
  /** null: this run has no result for the check. */
  a: boolean | null;
  b: boolean | null;
  changed: boolean;
}

/**
 * Results keyed by evaluator name. Names can repeat within a run (an unnamed
 * evaluator is named after its type), so the second `file_contains` is keyed
 * `file_contains #2`: repeated checks are matched by order, never merged.
 */
function byName(evaluation: EvaluationResult | null): Map<string, boolean> {
  const seen = new Map<string, number>();
  const out = new Map<string, boolean>();
  for (const result of evaluation?.results ?? []) {
    const n = (seen.get(result.name) ?? 0) + 1;
    seen.set(result.name, n);
    out.set(n === 1 ? result.name : `${result.name} #${n}`, result.passed);
  }
  return out;
}

/** Evaluator results by name: A's order first, then checks only B has. */
export function checkRows(a: EvaluationResult | null, b: EvaluationResult | null): CheckRow[] {
  const inA = byName(a);
  const inB = byName(b);
  const names = [...inA.keys(), ...[...inB.keys()].filter((name) => !inA.has(name))];
  return names.map((name) => {
    const pa = inA.get(name) ?? null;
    const pb = inB.get(name) ?? null;
    return { name, a: pa, b: pb, changed: pa !== pb };
  });
}

/** JSON with object keys sorted, so equal values always print the same. */
export function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== undefined)
      .sort(([x], [y]) => (x < y ? -1 : x > y ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stableJson(v)}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

function flatten(value: unknown, prefix: string, out: Map<string, string>): void {
  const isObject = value !== null && typeof value === "object" && !Array.isArray(value);
  if (isObject && Object.keys(value as object).length > 0) {
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      flatten(child, prefix ? `${prefix}.${key}` : key, out);
    }
  } else if (prefix) {
    out.set(prefix, stableJson(value));
  }
}

export interface ConfigDiffRow {
  /** Dotted path into the configuration, e.g. `limits.max_steps`. */
  path: string;
  /** JSON text of the value; null when the path does not exist on that side. */
  a: string | null;
  b: string | null;
}

/** Leaf paths whose values differ between two configuration snapshots. Lists are compared whole. */
export function configDiff(a: unknown, b: unknown): ConfigDiffRow[] {
  const fa = new Map<string, string>();
  const fb = new Map<string, string>();
  flatten(a, "", fa);
  flatten(b, "", fb);
  const paths = [...new Set([...fa.keys(), ...fb.keys()])].sort();
  const rows: ConfigDiffRow[] = [];
  for (const path of paths) {
    const va = fa.get(path) ?? null;
    const vb = fb.get(path) ?? null;
    if (va !== vb) rows.push({ path, a: va, b: vb });
  }
  return rows;
}

export interface CallDigest {
  tool: string;
  /** Stable JSON of the arguments, with the run's workspace path replaced. */
  args: string;
  status: ToolCallStatus;
}

export interface StepDigest {
  index: number;
  kind: Step["kind"];
  calls: CallDigest[];
  error: string | null;
  /** Evaluation steps: whether the evaluation passed. */
  passed: boolean | null;
}

/**
 * - `same`: same kind, same tool calls with the same arguments and outcomes;
 * - `different_outcome`: same calls, but a status, error or evaluation differs;
 * - `different`: the calls themselves differ;
 * - `only_a` / `only_b`: the other run has no step at this position.
 */
export type StepRelation = "same" | "different_outcome" | "different" | "only_a" | "only_b";

export interface StepPair {
  position: number;
  a: StepDigest | null;
  b: StepDigest | null;
  relation: StepRelation;
}

export function digestStep(step: Step, workspace: string | null): StepDigest {
  return {
    index: step.index,
    kind: step.kind,
    calls: step.tool_calls.map((call) => {
      const args = stableJson(call.arguments);
      return {
        tool: call.tool,
        // Each run has its own workspace directory; an argument naming it is
        // the same request in both runs.
        args: workspace ? args.split(workspace).join("<workspace>") : args,
        status: call.status,
      };
    }),
    error: step.error?.type ?? null,
    passed: step.evaluation ? step.evaluation.passed : null,
  };
}

function relate(a: StepDigest, b: StepDigest): StepRelation {
  const sameCalls =
    a.kind === b.kind &&
    a.calls.length === b.calls.length &&
    a.calls.every((call, i) => call.tool === b.calls[i]?.tool && call.args === b.calls[i]?.args);
  if (!sameCalls) return "different";
  const sameOutcome =
    a.error === b.error && a.passed === b.passed && a.calls.every((call, i) => call.status === b.calls[i]?.status);
  return sameOutcome ? "same" : "different_outcome";
}

/**
 * Pair the two runs' steps by position. The model's text is not compared:
 * two runs can word a turn differently and still do the same thing.
 */
export function alignSteps(a: Run, b: Run): StepPair[] {
  const da = a.steps.map((step) => digestStep(step, a.workspace));
  const db = b.steps.map((step) => digestStep(step, b.workspace));
  const pairs: StepPair[] = [];
  for (let i = 0; i < Math.max(da.length, db.length); i += 1) {
    const sa = da[i] ?? null;
    const sb = db[i] ?? null;
    const relation = sa && sb ? relate(sa, sb) : sa ? "only_a" : "only_b";
    pairs.push({ position: i, a: sa, b: sb, relation });
  }
  return pairs;
}

/** Position of the first pair that is not `same`, or null when the traces match. */
export function firstDivergence(pairs: StepPair[]): number | null {
  const pair = pairs.find((p) => p.relation !== "same");
  return pair ? pair.position : null;
}

export const RELATION_LABELS: Record<StepRelation, string> = {
  same: "same",
  different_outcome: "same calls, different outcome",
  different: "different",
  only_a: "only in A",
  only_b: "only in B",
};

/** Things that make a side-by-side reading misleading; shown above the comparison. */
export function comparisonCaveats(a: Run, b: Run): string[] {
  const caveats: string[] = [];
  if (a.id === b.id) caveats.push("Both sides are the same run.");
  if (a.goal !== b.goal) caveats.push("The runs have different goals, so their traces answer different questions.");
  if (stableJson(a.evaluators) !== stableJson(b.evaluators)) {
    caveats.push("The runs were evaluated with different checks; pass/fail and scores are not comparable.");
  }
  const terminal = new Set(["succeeded", "failed", "cancelled", "timed_out"]);
  if (!terminal.has(a.status) || !terminal.has(b.status)) {
    caveats.push("At least one run has not finished; its numbers are still changing.");
  }
  return caveats;
}

/** Signed difference text for a metric row; "—" when it cannot be computed. */
export function formatMetricDelta(row: MetricRow): string {
  const d = row.delta;
  if (d === null || Number.isNaN(d)) return "—";
  if (d === 0) return "±0";
  const sign = d > 0 ? "+" : "−";
  const abs = Math.abs(d);
  switch (row.kind) {
    case "duration":
      return abs < 1 ? `${sign}${Math.round(abs * 1000)} ms` : `${sign}${abs.toFixed(1)} s`;
    case "percent": {
      const points = Math.round(abs * 1000) / 10;
      return points === 0 ? "±0" : `${sign}${points} pp`;
    }
    case "score":
      return `${sign}${abs.toFixed(2)}`;
    case "cost":
      return `${sign}$${abs < 0.01 ? abs.toFixed(4) : abs.toFixed(2)}`;
    default:
      return `${sign}${abs.toLocaleString("en-US")}`;
  }
}
