// Complete API objects for component tests; override only what a test is about.

import type { Agent, AgentConfig, DailyPoint, Run, RunSummary } from "@/lib/types";

export function agentConfig(overrides: Partial<AgentConfig> = {}): AgentConfig {
  return {
    name: "demo-agent",
    description: "",
    model: {
      provider: "scripted",
      model: "demo",
      temperature: null,
      max_tokens: 1024,
      base_url: null,
      api_key_env: null,
      options: {},
    },
    system_prompt: "",
    tools: ["filesystem"],
    tool_settings: {},
    limits: {
      max_steps: 10,
      timeout_seconds: 60,
      max_tool_calls: 20,
      max_consecutive_tool_errors: 3,
      max_output_chars: 10_000,
    },
    retry: {},
    planner: { strategy: "react", max_plan_steps: 8 },
    memory: {},
    sandbox: { kind: "local", image: "", network: "none", memory: "512m", cpus: 1 },
    labels: {},
    ...overrides,
  };
}

export function agent(overrides: Partial<Agent> = {}): Agent {
  const config = agentConfig();
  return {
    id: "agent_1",
    name: config.name,
    description: "",
    version: 1,
    created_at: "2026-11-01T10:00:00Z",
    updated_at: "2026-11-01T10:00:00Z",
    config,
    ...overrides,
  };
}

export function runSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: "run_1",
    agent_id: "agent_1",
    agent_name: "demo-agent",
    goal: "Write hello.txt",
    status: "succeeded",
    provider: "scripted",
    model: "demo",
    created_at: "2026-11-01T10:00:00Z",
    started_at: "2026-11-01T10:00:00Z",
    finished_at: "2026-11-01T10:00:02Z",
    duration_seconds: 2,
    steps: 3,
    tool_calls: 2,
    tool_success_rate: 1,
    input_tokens: 0,
    output_tokens: 0,
    cost_usd: null,
    passed: true,
    score: 1,
    error_type: null,
    labels: {},
    ...overrides,
  };
}

export function run(overrides: Partial<Run> = {}): Run {
  return {
    id: "run_1",
    agent_id: "agent_1",
    agent_name: "demo-agent",
    config: agentConfig(),
    goal: "Write hello.txt",
    status: "succeeded",
    created_at: "2026-11-01T10:00:00Z",
    started_at: "2026-11-01T10:00:00Z",
    finished_at: "2026-11-01T10:00:02Z",
    steps: [],
    plan: null,
    result: "Done.",
    error: null,
    usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 },
    evaluation: null,
    metrics: {
      duration_seconds: 2,
      steps: 3,
      llm_calls: 3,
      llm_retries: 0,
      evaluation_retries: 0,
      tool_calls: 2,
      tool_errors: 0,
      tool_success_rate: 1,
      errors: 0,
      input_tokens: 0,
      output_tokens: 0,
      cost_usd: null,
    },
    workspace: null,
    labels: {},
    parent_run_id: null,
    evaluators: [],
    ...overrides,
  };
}

export function dailyPoint(date: string, overrides: Partial<DailyPoint> = {}): DailyPoint {
  return {
    date,
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
