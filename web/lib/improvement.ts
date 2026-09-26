// Pure helpers for the improvement-loop views (unit-tested in improvement.test.ts).

import type { BenchmarkRun, CycleStatus, ImprovementCycle, ProposedChange, ResultClass } from "./types.ts";

/** Human labels for failure categories, in the order they are usually worth fixing. */
export const CATEGORY_LABELS: Record<string, string> = {
  tests_failed: "Tests failed",
  workspace_state: "Wrong files / content",
  wrong_output: "Wrong final answer",
  no_final_answer: "No final answer",
  process_not_followed: "Process not followed",
  judge_rejected: "Rejected by judge",
  step_limit: "Step limit reached",
  timeout: "Timed out",
  tool_budget: "Tool budget exhausted",
  tool_errors: "Repeated tool errors",
  inefficient: "Too many steps",
  llm_error: "Provider error",
  llm_refusal: "Model refused",
  evaluation_failed: "Custom check failed",
  not_evaluated: "Not evaluated",
  setup: "Task setup failed",
  internal: "Internal error",
  cancelled: "Cancelled",
  missing_record: "Run record missing",
};

/** Categories caused by the environment or operator rather than the agent. */
export const NON_AGENT_CATEGORIES = new Set(["setup", "internal", "cancelled", "missing_record"]);

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category.replaceAll("_", " ");
}

/** Category counts as sorted rows (largest first, then by name). */
export function categoryRows(counts: Record<string, number>): { category: string; count: number; share: number }[] {
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
  return Object.entries(counts)
    .filter(([, n]) => n > 0)
    .sort(([a, x], [b, y]) => y - x || a.localeCompare(b))
    .map(([category, count]) => ({ category, count, share: total ? count / total : 0 }));
}

export function resultClassOf(bench: Pick<BenchmarkRun, "result_class" | "agent_config">): ResultClass {
  if (bench.result_class) return bench.result_class;
  return bench.agent_config.model.provider === "scripted" ? "offline" : "real";
}

/** Split benchmark runs into the two classes that must never be mixed. */
export function splitByResultClass<T extends Pick<BenchmarkRun, "result_class" | "agent_config">>(
  runs: T[],
): Record<ResultClass, T[]> {
  const out: Record<ResultClass, T[]> = { offline: [], real: [] };
  for (const run of runs) out[resultClassOf(run)].push(run);
  return out;
}

export function formatValue(value: unknown, max = 80): string {
  if (value === null || value === undefined) return "—";
  const text = typeof value === "string" ? value : JSON.stringify(value);
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}

export function describeChange(change: Pick<ProposedChange, "path" | "operation" | "value" | "current">): string {
  if (change.operation === "append") return `${change.path} += ${formatValue(change.value, 60)}`;
  return `${change.path}: ${formatValue(change.current, 30)} → ${formatValue(change.value, 30)}`;
}

/** Which actions a cycle allows in its current state. */
export function cycleActions(cycle: Pick<ImprovementCycle, "status" | "proposal">): {
  apply: boolean;
  evaluate: boolean;
  reject: boolean;
} {
  const status: CycleStatus = cycle.status;
  return {
    apply: status === "proposed" && cycle.proposal.changes.length > 0,
    evaluate: status === "applied",
    reject: status === "proposed" || status === "applied" || status === "evaluated" || status === "failed",
  };
}

export interface ConfigChange {
  path: string;
  before: unknown;
  after: unknown;
}

function flatten(value: unknown, prefix: string, out: Map<string, unknown>): void {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0 && prefix) out.set(prefix, value);
    for (const [key, child] of entries) flatten(child, prefix ? `${prefix}.${key}` : key, out);
    return;
  }
  out.set(prefix, value);
}

/** Leaf-level differences between two configs (arrays compared as values). */
export function configDiff(before: unknown, after: unknown): ConfigChange[] {
  const a = new Map<string, unknown>();
  const b = new Map<string, unknown>();
  flatten(before, "", a);
  flatten(after, "", b);
  const paths = [...new Set([...a.keys(), ...b.keys()])].sort();
  return paths
    .filter((path) => JSON.stringify(a.get(path)) !== JSON.stringify(b.get(path)))
    .map((path) => ({ path, before: a.get(path), after: b.get(path) }));
}
