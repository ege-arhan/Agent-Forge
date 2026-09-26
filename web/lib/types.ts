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
  agent_id?: string | null;
  agent_version?: number | null;
  result_class?: ResultClass;
  /** Snapshot of the suite definition the run used. */
  suite: { id: string; name: string; version: string };
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

// ------------------------------------------------------------ improvement loop

/** Offline (scripted provider) and real-model results are never mixed. */
export type ResultClass = "offline" | "real";

export type AgentVersionSource = "created" | "updated" | "improvement" | "revert";

export interface AgentVersion {
  agent_id: string;
  version: number;
  config: AgentConfig;
  source: AgentVersionSource;
  change_summary: string;
  improvement_id: string | null;
  parent_version: number | null;
  created_at: string;
}

export interface TaskFailure {
  task_id: string;
  repeat: number;
  run_id: string;
  category: string;
  secondary: string[];
  summary: string;
  evidence: string[];
}

export interface FailureAnalysis {
  benchmark_run_id: string;
  suite_id: string;
  suite_version: string;
  result_class: ResultClass;
  agent_name: string;
  agent_id: string | null;
  agent_version: number | null;
  runs: number;
  passed: number;
  failed: number;
  categories: Record<string, number>;
  tool_issues: Record<string, Record<string, number>>;
  tasks: { task_id: string; runs: number; passed: number; categories: Record<string, number> }[];
  failures: TaskFailure[];
}

export interface ProposedChange {
  id: string;
  path: string;
  operation: "set" | "append";
  value: unknown;
  current: unknown;
  rationale: string;
  addresses: string[];
  evidence: string[];
}

export interface ImprovementProposal {
  proposer: string;
  changes: ProposedChange[];
  notes: string[];
}

export type Verdict = "improved" | "regressed" | "unchanged" | "inconclusive" | "not_comparable";

export interface ComparisonSide {
  benchmark_run_id: string;
  agent_name: string;
  agent_version: number | null;
  provider: string;
  model: string;
  runs: number;
  passed: number;
  pass_rate: number;
  pass_rate_ci95: [number, number] | null;
  mean_score: number;
  mean_steps: number | null;
  mean_duration_seconds: number | null;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number | null;
}

export interface BenchmarkComparison {
  baseline_id: string;
  candidate_id: string;
  suite_id: string;
  suite_version: string;
  result_class: ResultClass;
  comparable: boolean;
  reasons: string[];
  notes: string[];
  baseline: ComparisonSide | null;
  candidate: ComparisonSide | null;
  pass_rate_delta: number | null;
  mean_score_delta: number | null;
  mean_steps_delta: number | null;
  significant: boolean;
  verdict: Verdict;
  tasks: {
    task_id: string;
    baseline_passed: number;
    baseline_runs: number;
    candidate_passed: number;
    candidate_runs: number;
    pass_rate_delta: number;
    change: "fixed" | "broken" | "better" | "worse" | "unchanged";
  }[];
  categories: { category: string; baseline: number; candidate: number }[];
}

export type CycleStatus = "proposed" | "applied" | "evaluating" | "evaluated" | "rejected" | "failed";

export interface ImprovementCycle {
  id: string;
  agent_id: string;
  agent_name: string;
  status: CycleStatus;
  suite_id: string;
  suite_version: string;
  result_class: ResultClass;
  task_ids: string[];
  repeats: number;
  from_version: number;
  to_version: number | null;
  reverted_to_version: number | null;
  baseline_benchmark_run_id: string;
  candidate_benchmark_run_id: string | null;
  analysis: FailureAnalysis;
  proposal: ImprovementProposal;
  applied_change_ids: string[];
  comparison: BenchmarkComparison | null;
  notes: string;
  error: string | null;
  created_at: string;
  updated_at: string;
}
