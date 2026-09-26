// Types mirroring the AgentForge HTTP API (src/agentforge/api, core/models.py).

export type RunStatus = "pending" | "running" | "succeeded" | "failed" | "cancelled" | "timed_out";

export type ToolCallStatus = "success" | "error" | "denied" | "timeout" | "invalid_input";

export interface ModelConfig {
  provider: string;
  model: string;
  temperature: number | null;
  max_tokens: number;
  base_url: string | null;
  api_key_env: string | null;
  options: Record<string, unknown>;
}

export interface AgentConfig {
  name: string;
  description: string;
  model: ModelConfig;
  system_prompt: string;
  tools: string[];
  tool_settings: Record<string, Record<string, unknown>>;
  limits: {
    max_steps: number;
    timeout_seconds: number;
    max_tool_calls: number;
    max_consecutive_tool_errors: number;
    max_output_chars: number;
  };
  retry: Record<string, number>;
  planner: { strategy: string; max_plan_steps: number };
  memory: Record<string, unknown>;
  sandbox: { kind: string; image: string; network: string; memory: string; cpus: number };
  labels: Record<string, string>;
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  version: number;
  created_at: string;
  updated_at: string;
  config: AgentConfig;
}

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
}

export interface ErrorInfo {
  type: string;
  message: string;
  retryable: boolean;
}

export interface LLMCallRecord {
  provider: string;
  model: string;
  started_at: string;
  finished_at: string;
  latency_ms: number;
  attempts: number;
  stop_reason: string | null;
  usage: TokenUsage;
  cost_usd: number | null;
  error: ErrorInfo | null;
}

export interface ToolCallRecord {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  status: ToolCallStatus;
  output: string;
  error: string | null;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  truncated: boolean;
}

export interface EvaluatorResult {
  name: string;
  passed: boolean;
  score: number;
  weight: number;
  required: boolean;
  details: string;
  metrics: Record<string, number>;
}

export interface EvaluationResult {
  passed: boolean;
  score: number;
  results: EvaluatorResult[];
  evaluated_at: string;
}

export interface Step {
  index: number;
  kind: "plan" | "action" | "evaluation";
  started_at: string;
  finished_at: string | null;
  thought: string;
  llm_call: LLMCallRecord | null;
  tool_calls: ToolCallRecord[];
  plan: string[] | null;
  evaluation: EvaluationResult | null;
  error: ErrorInfo | null;
}

export interface RunMetrics {
  duration_seconds: number | null;
  steps: number;
  llm_calls: number;
  llm_retries: number;
  evaluation_retries: number;
  tool_calls: number;
  tool_errors: number;
  tool_success_rate: number | null;
  errors: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
}

export interface Run {
  id: string;
  agent_id: string | null;
  agent_name: string;
  config: AgentConfig;
  goal: string;
  status: RunStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  steps: Step[];
  plan: string[] | null;
  result: string | null;
  error: ErrorInfo | null;
  usage: TokenUsage;
  evaluation: EvaluationResult | null;
  metrics: RunMetrics;
  workspace: string | null;
  labels: Record<string, string>;
  parent_run_id: string | null;
  evaluators: Record<string, unknown>[];
}

export interface RunSummary {
  id: string;
  agent_id: string | null;
  agent_name: string;
  goal: string;
  status: RunStatus;
  provider: string;
  model: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  steps: number;
  tool_calls: number;
  tool_success_rate: number | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  passed: boolean | null;
  score: number | null;
  error_type: string | null;
  labels: Record<string, string>;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export interface Stats {
  runs_by_status: Record<string, number>;
  total_runs: number;
  active_runs: number;
  completion_rate: number | null;
  evaluated_runs: number;
  evaluation_pass_rate: number | null;
  mean_evaluation_score: number | null;
  tool_calls: Record<string, Record<string, number>>;
  known_cost_usd: number;
  runs_with_unknown_cost: number;
  input_tokens: number;
  output_tokens: number;
}

export interface SuiteTask {
  id: string;
  goal: string;
  expected_behavior: string;
  allowed_tools: string[] | null;
  evaluators: Record<string, unknown>[];
  tags: string[];
}

export interface Suite {
  id: string;
  name: string;
  description: string;
  version: string;
  repeats: number;
  tasks: SuiteTask[];
  path: string;
}

export interface TaskRunResult {
  task_id: string;
  repeat: number;
  run_id: string;
  status: RunStatus;
  passed: boolean;
  score: number;
  duration_seconds: number | null;
  steps: number;
  tool_calls: number;
  tool_success_rate: number | null;
  llm_retries: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  error: string | null;
}

export interface TaskSummary {
  task_id: string;
  runs: number;
  passed: number;
  pass_rate: number;
  mean_score: number;
  score_stddev: number | null;
  mean_duration_seconds: number | null;
  mean_steps: number | null;
}

export interface BenchmarkSummary {
  runs: number;
  passed: number;
  pass_rate: number;
  pass_rate_ci95: [number, number] | null;
  mean_score: number;
  score_stddev: number | null;
  mean_duration_seconds: number | null;
  mean_steps: number | null;
  mean_tool_success_rate: number | null;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number | null;
  errors: number;
  tasks: TaskSummary[];
}

export interface BenchmarkRun {
  id: string;
  suite_id: string;
  suite_name: string;
  agent_name: string;
  agent_config: AgentConfig;
  status: RunStatus;
  created_at: string;
  finished_at: string | null;
  repeats: number;
  results: TaskRunResult[];
  summary: BenchmarkSummary | null;
  experiment_id: string | null;
  variant: string | null;
  environment: Record<string, unknown>;
}

export interface VariantResult {
  variant: string;
  benchmark_run_id: string;
  provider: string;
  model: string;
  summary: BenchmarkSummary | null;
  status: RunStatus;
}

export interface Experiment {
  id: string;
  name: string;
  description: string;
  status: RunStatus;
  created_at: string;
  finished_at: string | null;
  spec: {
    name: string;
    variants: { name: string; description: string; overrides: Record<string, unknown> }[];
    repeats: number | null;
    task_ids: string[] | null;
  };
  suite_id: string;
  variants: VariantResult[];
}

export interface ComparisonRow {
  variant: string;
  runs: number;
  pass_rate: number;
  pass_rate_ci95: [number, number] | null;
  mean_score: number;
  mean_duration_seconds: number | null;
  mean_steps: number | null;
  total_cost_usd: number | null;
  pass_rate_delta: number | null;
  task_pass_rates: Record<string, number>;
}

export interface ToolInfo {
  name: string;
  description: string;
  toolset: string | null;
  permissions: string[];
  timeout_seconds: number;
  input_schema: Record<string, unknown>;
}

export interface ProviderInfo {
  name: string;
  description: string;
  api_key_env: string | null;
  requires_model: boolean;
}

export interface EvaluatorInfo {
  type: string;
  description: string;
  params_schema: Record<string, unknown>;
}

export interface Issue {
  number: number;
  title: string;
  body: string | null;
  state: string;
  html_url: string;
  labels: string[];
  user: string | null;
  is_pull_request: boolean;
}

export interface Health {
  status: string;
  version: string;
  database: string;
}
