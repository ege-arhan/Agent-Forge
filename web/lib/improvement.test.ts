import assert from "node:assert/strict";
import { test } from "node:test";

import {
  categoryLabel,
  categoryRows,
  configDiff,
  cycleActions,
  describeChange,
  formatValue,
  resultClassOf,
  splitByResultClass,
} from "./improvement.ts";
import type { AgentConfig } from "./types.ts";

const config = (provider: string) => ({ model: { provider, model: "m" } }) as unknown as AgentConfig;

test("category labels fall back to readable text", () => {
  assert.equal(categoryLabel("step_limit"), "Step limit reached");
  assert.equal(categoryLabel("brand_new"), "brand new");
});

test("category rows are sorted by count and carry shares", () => {
  const rows = categoryRows({ timeout: 1, step_limit: 3, tests_failed: 0, setup: 1 });
  assert.deepEqual(
    rows.map((r) => r.category),
    ["step_limit", "setup", "timeout"],
  );
  assert.equal(rows[0]?.share, 0.6);
  assert.deepEqual(categoryRows({}), []);
});

test("result class is derived and runs are split, never mixed", () => {
  assert.equal(resultClassOf({ agent_config: config("scripted") }), "offline");
  assert.equal(resultClassOf({ agent_config: config("anthropic") }), "real");
  assert.equal(resultClassOf({ agent_config: config("anthropic"), result_class: "offline" }), "offline");
  const split = splitByResultClass([
    { agent_config: config("scripted") },
    { agent_config: config("openai") },
    { agent_config: config("scripted"), result_class: "offline" as const },
  ]);
  assert.equal(split.offline.length, 2);
  assert.equal(split.real.length, 1);
});

test("changes are described compactly", () => {
  assert.equal(
    describeChange({ path: "limits.max_steps", operation: "set", current: 3, value: 20 }),
    "limits.max_steps: 3 → 20",
  );
  assert.match(
    describeChange({ path: "system_prompt", operation: "append", current: null, value: "Run the tests.\nAlways." }),
    /^system_prompt \+= Run the tests\. Always\.$/,
  );
  assert.equal(formatValue(null), "—");
  assert.equal(formatValue("x".repeat(100), 10), `${"x".repeat(9)}…`);
});

test("cycle actions follow the lifecycle", () => {
  const proposal = { proposer: "rules", changes: [{}] as never[], notes: [] };
  assert.deepEqual(cycleActions({ status: "proposed", proposal }), { apply: true, evaluate: false, reject: true });
  assert.deepEqual(cycleActions({ status: "proposed", proposal: { ...proposal, changes: [] } }).apply, false);
  assert.deepEqual(cycleActions({ status: "applied", proposal }), { apply: false, evaluate: true, reject: true });
  assert.deepEqual(cycleActions({ status: "evaluating", proposal }), { apply: false, evaluate: false, reject: false });
  assert.equal(cycleActions({ status: "rejected", proposal }).reject, false);
});

test("config diff lists changed leaves", () => {
  const before = { name: "a", limits: { max_steps: 3, timeout_seconds: 60 }, tools: ["fs"], labels: {} };
  const after = { name: "a", limits: { max_steps: 20, timeout_seconds: 60 }, tools: ["fs", "git"], labels: {} };
  assert.deepEqual(configDiff(before, after), [
    { path: "limits.max_steps", before: 3, after: 20 },
    { path: "tools", before: ["fs"], after: ["fs", "git"] },
  ]);
  assert.deepEqual(configDiff(before, before), []);
  assert.deepEqual(configDiff({ a: 1 }, { b: 2 }), [
    { path: "a", before: 1, after: undefined },
    { path: "b", before: undefined, after: 2 },
  ]);
});
