import assert from "node:assert/strict";
import { test } from "node:test";

import {
  alignSteps,
  checkRows,
  compareHref,
  comparisonCaveats,
  configDiff,
  firstDivergence,
  formatMetricDelta,
  metricRows,
  stableJson,
  toggleSelection,
} from "./compare.ts";
import type { EvaluationResult, Run, Step, ToolCallRecord, ToolCallStatus } from "./types.ts";

function call(tool: string, args: Record<string, unknown>, status: ToolCallStatus = "success"): ToolCallRecord {
  return {
    id: `${tool}-1`,
    tool,
    arguments: args,
    status,
    output: "",
    error: null,
    started_at: "2026-01-01T00:00:00Z",
    finished_at: "2026-01-01T00:00:01Z",
    duration_ms: 10,
    truncated: false,
  };
}

function step(index: number, calls: ToolCallRecord[], extra: Partial<Step> = {}): Step {
  return {
    index,
    kind: "action",
    started_at: "2026-01-01T00:00:00Z",
    finished_at: "2026-01-01T00:00:01Z",
    thought: "",
    llm_call: null,
    tool_calls: calls,
    plan: null,
    evaluation: null,
    error: null,
    ...extra,
  };
}

function evaluation(results: Record<string, boolean>, score = 1): EvaluationResult {
  return {
    passed: Object.values(results).every(Boolean),
    score,
    evaluated_at: "2026-01-01T00:00:02Z",
    results: Object.entries(results).map(([name, passed]) => ({
      name,
      passed,
      score: passed ? 1 : 0,
      weight: 1,
      required: true,
      details: "",
      metrics: {},
    })),
  };
}

function run(id: string, extra: Partial<Run> = {}): Run {
  return {
    id,
    agent_id: null,
    agent_name: "agent",
    config: { limits: { max_steps: 8 }, tools: ["read_file"], model: { provider: "scripted", model: "m" } },
    goal: "fix the bug",
    status: "succeeded",
    created_at: "2026-01-01T00:00:00Z",
    started_at: null,
    finished_at: null,
    steps: [],
    plan: null,
    result: null,
    error: null,
    usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 },
    evaluation: null,
    metrics: {
      duration_seconds: 2,
      steps: 3,
      llm_calls: 3,
      llm_retries: 0,
      evaluation_retries: 0,
      tool_calls: 4,
      tool_errors: 0,
      tool_success_rate: 1,
      errors: 0,
      input_tokens: 100,
      output_tokens: 50,
      cost_usd: null,
    },
    workspace: `/tmp/ws/${id}`,
    labels: {},
    parent_run_id: null,
    evaluators: [],
    ...extra,
  } as unknown as Run;
}

test("toggleSelection keeps the two most recent ids and deselects on a second click", () => {
  assert.deepEqual(toggleSelection([], "a"), ["a"]);
  assert.deepEqual(toggleSelection(["a"], "b"), ["a", "b"]);
  assert.deepEqual(toggleSelection(["a", "b"], "c"), ["b", "c"]);
  assert.deepEqual(toggleSelection(["a", "b"], "a"), ["b"]);
});

test("compareHref encodes both ids", () => {
  assert.equal(compareHref("run_1", "run 2"), "/runs/compare?a=run_1&b=run%202");
});

test("metricRows reports b - a and never invents a delta for unknown values", () => {
  const a = run("a");
  const b = run("b", {
    metrics: { ...run("b").metrics, steps: 5, duration_seconds: 1.5, cost_usd: 0.02 },
    evaluation: evaluation({ tests: true }, 0.75),
  });
  const rows = Object.fromEntries(metricRows(a, b).map((r) => [r.key, r]));
  assert.equal(rows.steps?.delta, 2);
  assert.equal(rows.duration?.delta, -0.5);
  // A's cost is unknown: no delta, not "+$0.02".
  assert.equal(rows.cost?.a, null);
  assert.equal(rows.cost?.delta, null);
  // A was not evaluated.
  assert.equal(rows.score?.a, null);
  assert.equal(rows.score?.delta, null);
});

test("formatMetricDelta formats by kind", () => {
  const row = (kind: Parameters<typeof formatMetricDelta>[0]["kind"], delta: number | null) =>
    formatMetricDelta({ key: "k", label: "l", kind, a: 0, b: 0, delta });
  assert.equal(row("count", 2), "+2");
  assert.equal(row("count", -1200), "−1,200");
  assert.equal(row("count", 0), "±0");
  assert.equal(row("count", null), "—");
  assert.equal(row("duration", -0.5), "−500 ms");
  assert.equal(row("duration", 12.34), "+12.3 s");
  assert.equal(row("percent", -0.25), "−25 pp");
  assert.equal(row("percent", 0.00001), "±0");
  assert.equal(row("score", 0.5), "+0.50");
  assert.equal(row("cost", 0.004), "+$0.0040");
  assert.equal(row("cost", -1.5), "−$1.50");
});

test("checkRows unions evaluator results by name and marks changes", () => {
  const rows = checkRows(evaluation({ tests: false, lint: true }), evaluation({ tests: true, lint: true, docs: false }));
  assert.deepEqual(rows, [
    { name: "tests", a: false, b: true, changed: true },
    { name: "lint", a: true, b: true, changed: false },
    { name: "docs", a: null, b: false, changed: true },
  ]);
  assert.deepEqual(checkRows(null, null), []);
});

test("stableJson ignores key order", () => {
  assert.equal(stableJson({ b: 1, a: [{ d: 2, c: 1 }] }), stableJson({ a: [{ c: 1, d: 2 }], b: 1 }));
  assert.equal(stableJson({ a: undefined, b: null }), '{"b":null}');
});

test("configDiff lists only differing leaf paths", () => {
  const a = { limits: { max_steps: 8, timeout_seconds: 60 }, tools: ["read_file"], labels: {}, model: { model: "m" } };
  const b = { limits: { timeout_seconds: 60, max_steps: 25 }, tools: ["read_file", "run_command"], labels: {}, model: { model: "m" }, stream: true };
  assert.deepEqual(configDiff(a, b), [
    { path: "limits.max_steps", a: "8", b: "25" },
    { path: "stream", a: null, b: "true" },
    { path: "tools", a: '["read_file"]', b: '["read_file","run_command"]' },
  ]);
  assert.deepEqual(configDiff(a, a), []);
});

test("configDiff reports an object that became empty", () => {
  assert.deepEqual(configDiff({ labels: { team: "x" } }, { labels: {} }), [
    { path: "labels", a: null, b: "{}" },
    { path: "labels.team", a: '"x"', b: null },
  ]);
});

test("alignSteps finds the first step where the tool calls differ", () => {
  const a = run("a", {
    steps: [
      step(1, [call("read_file", { path: "calc.py" })]),
      step(2, [call("write_file", { path: "calc.py", content: "x" })]),
      step(3, [call("run_command", { command: "pytest" })]),
    ],
  });
  const b = run("b", {
    steps: [
      step(1, [call("read_file", { path: "calc.py" })]),
      step(2, [call("run_command", { command: "pytest" })]),
    ],
  });
  const pairs = alignSteps(a, b);
  assert.deepEqual(
    pairs.map((p) => p.relation),
    ["same", "different", "only_a"],
  );
  assert.equal(firstDivergence(pairs), 1);
  assert.equal(pairs[2]?.b, null);
});

test("alignSteps treats each run's own workspace path as the same argument", () => {
  const a = run("a", { steps: [step(1, [call("run_command", { cwd: "/tmp/ws/a", command: "ls" })])] });
  const b = run("b", { steps: [step(1, [call("run_command", { command: "ls", cwd: "/tmp/ws/b" })])] });
  const pairs = alignSteps(a, b);
  assert.equal(pairs[0]?.relation, "same");
  assert.equal(firstDivergence(pairs), null);
  assert.match(pairs[0]?.a?.calls[0]?.args ?? "", /<workspace>/);
});

test("alignSteps separates a different outcome from different calls", () => {
  const calls = () => [call("run_command", { command: "pytest" })];
  const a = run("a", { steps: [step(1, calls()), step(2, [], { kind: "evaluation", evaluation: evaluation({ t: true }) })] });
  const b = run("b", {
    steps: [
      step(1, [call("run_command", { command: "pytest" }, "error")]),
      step(2, [], { kind: "evaluation", evaluation: evaluation({ t: false }) }),
    ],
  });
  assert.deepEqual(
    alignSteps(a, b).map((p) => p.relation),
    ["different_outcome", "different_outcome"],
  );
  // The model's wording is not compared.
  const c = run("c", { steps: [step(1, calls(), { thought: "one" })] });
  const d = run("d", { steps: [step(1, calls(), { thought: "two" })] });
  assert.equal(alignSteps(c, d)[0]?.relation, "same");
});

test("comparisonCaveats flags comparisons that would mislead", () => {
  assert.deepEqual(comparisonCaveats(run("a"), run("b")), []);
  assert.equal(comparisonCaveats(run("a"), run("a")).length, 1);
  const caveats = comparisonCaveats(
    run("a", { goal: "other", evaluators: [{ type: "contains" }] }),
    run("b", { status: "running" }),
  );
  assert.equal(caveats.length, 3);
  assert.match(caveats[0] ?? "", /different goals/);
  assert.match(caveats[1] ?? "", /different checks/);
  assert.match(caveats[2] ?? "", /not finished/);
});
