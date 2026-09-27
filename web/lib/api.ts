// Minimal typed client for the AgentForge HTTP API.

import type {
  Agent,
  AgentConfig,
  AgentVersion,
  BenchmarkComparison,
  BenchmarkRun,
  ComparisonRow,
  EvaluatorInfo,
  Experiment,
  FailureAnalysis,
  GateResult,
  Health,
  ImprovementCycle,
  Issue,
  Page,
  PendingApproval,
  ProposedChange,
  ProviderInfo,
  Run,
  RunSummary,
  Stats,
  Suite,
  ToolInfo,
} from "./types.ts";

const DEFAULT_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const STORAGE_KEY = "agentforge.connection";

export interface Connection {
  baseUrl: string;
  apiKey: string;
}

export function loadConnection(): Connection {
  if (typeof window === "undefined") return { baseUrl: DEFAULT_BASE_URL, apiKey: "" };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<Connection>;
      return { baseUrl: parsed.baseUrl || DEFAULT_BASE_URL, apiKey: parsed.apiKey ?? "" };
    }
  } catch {
    // storage unavailable (private mode) - fall back to defaults
  }
  return { baseUrl: DEFAULT_BASE_URL, apiKey: "" };
}

export function saveConnection(connection: Connection): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(connection));
  } catch {
    // ignore: settings then only last for this page view
  }
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function buildUrl(baseUrl: string, path: string, query?: Record<string, unknown>): string {
  const url = new URL(`/api/v1${path}`, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, String(v)));
    else url.searchParams.set(key, String(value));
  }
  return url.toString();
}

export function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => {
          const item = d as { loc?: unknown[]; msg?: string };
          return `${(item.loc ?? []).slice(1).join(".")}: ${item.msg ?? ""}`.trim();
        })
        .join("; ");
    }
  }
  return `request failed with status ${status}`;
}

export async function request<T>(
  path: string,
  init: { method?: string; body?: unknown; query?: Record<string, unknown> } = {},
): Promise<T> {
  const { baseUrl, apiKey } = loadConnection();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  let response: Response;
  try {
    response = await fetch(buildUrl(baseUrl, path, init.query), {
      method: init.method ?? "GET",
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, `cannot reach the AgentForge API at ${baseUrl}`);
  }
  if (response.status === 204) return undefined as T;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, errorMessage(body, response.status));
  return body as T;
}

export const api = {
  health: () => request<Health>("/health"),
  stats: () => request<Stats>("/stats"),
  providers: () => request<ProviderInfo[]>("/providers"),
  tools: () => request<{ tools: ToolInfo[]; toolsets: Record<string, string[]> }>("/tools"),
  evaluators: () => request<EvaluatorInfo[]>("/evaluators"),

  agents: () => request<Agent[]>("/agents"),
  agent: (id: string) => request<Agent>(`/agents/${id}`),
  createAgent: (config: AgentConfig) => request<Agent>("/agents", { method: "POST", body: config }),
  deleteAgent: (id: string) => request<void>(`/agents/${id}`, { method: "DELETE" }),
  agentVersions: (id: string) => request<AgentVersion[]>(`/agents/${id}/versions`),

  failureCategories: () => request<Record<string, string>>("/improvements/categories"),
  improvements: (query: { agent_id?: string; limit?: number } = {}) =>
    request<ImprovementCycle[]>("/improvements", { query }),
  improvement: (id: string) => request<ImprovementCycle>(`/improvements/${id}`),
  proposeImprovement: (body: { benchmark_run_id: string; changes?: Partial<ProposedChange>[]; notes?: string }) =>
    request<ImprovementCycle>("/improvements", { method: "POST", body }),
  applyImprovement: (id: string, change_ids?: string[]) =>
    request<ImprovementCycle>(`/improvements/${id}/apply`, { method: "POST", body: { change_ids } }),
  evaluateImprovement: (id: string) =>
    request<ImprovementCycle>(`/improvements/${id}/evaluate`, { method: "POST" }),
  rejectImprovement: (id: string, reason = "") =>
    request<ImprovementCycle>(`/improvements/${id}/reject`, { method: "POST", body: { reason } }),

  runs: (query: { status?: string; agent_id?: string; benchmark_run_id?: string; limit?: number; offset?: number }) =>
    request<Page<RunSummary>>("/runs", { query }),
  run: (id: string) => request<Run>(`/runs/${id}`),
  createRun: (body: { goal: string; agent_id: string; evaluators?: unknown[] }) =>
    request<Run>("/runs", { method: "POST", body }),
  cancelRun: (id: string) => request<Run>(`/runs/${id}/cancel`, { method: "POST" }),
  rerun: (id: string) => request<Run>(`/runs/${id}/rerun`, { method: "POST" }),
  pendingApprovals: (id: string) => request<PendingApproval[]>(`/runs/${id}/approvals`),
  decideApproval: (id: string, callId: string, approved: boolean, reason?: string) =>
    request<Run>(`/runs/${id}/approvals/${callId}`, { method: "POST", body: { approved, reason } }),

  suites: () => request<Suite[]>("/benchmarks/suites"),
  benchmarkRuns: (
    query: {
      suite_id?: string;
      experiment_id?: string;
      agent_id?: string;
      result_class?: "offline" | "real";
      limit?: number;
    } = {},
  ) => request<BenchmarkRun[]>("/benchmarks/runs", { query }),
  benchmarkAnalysis: (id: string) => request<FailureAnalysis>(`/benchmarks/runs/${id}/analysis`),
  compareBenchmarks: (baseline: string, candidate: string) =>
    request<BenchmarkComparison>("/benchmarks/compare", { query: { baseline, candidate } }),
  benchmarkGate: (baseline: string, candidate: string) =>
    request<GateResult>("/benchmarks/gate", { query: { baseline, candidate } }),
  benchmarkRun: (id: string) => request<BenchmarkRun>(`/benchmarks/runs/${id}`),
  startBenchmark: (body: { suite_id: string; agent_id: string; repeats?: number; task_ids?: string[] }) =>
    request<BenchmarkRun>("/benchmarks/runs", { method: "POST", body }),

  experiments: () => request<Experiment[]>("/experiments"),
  experiment: (id: string) =>
    request<{ experiment: Experiment; comparison: ComparisonRow[] }>(`/experiments/${id}`),

  githubStatus: () => request<{ token_configured: boolean; token_env: string }>("/github/status"),
  githubRepo: (repo: string) => request<Record<string, unknown>>(`/github/repos/${repo}`),
  githubIssues: (repo: string, state = "open") =>
    request<Issue[]>(`/github/repos/${repo}/issues`, { query: { state } }),
  githubTasks: () => request<Page<RunSummary>>("/github/tasks"),
  startGithubTask: (body: {
    repo: string;
    issue_number: number;
    agent_id: string;
    test_command?: string;
    push: boolean;
    open_pr: boolean;
  }) => request<Run>("/github/tasks", { method: "POST", body }),
};
