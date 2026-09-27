# AgentForge Architecture

AgentForge is an agent *engineering* platform: it assembles agents from
declarative configs, executes them in sandboxes with an instrumented runtime,
records everything they do, evaluates the outcome with deterministic checks,
and runs repeatable benchmarks and experiments across configurations.

## Component map

```mermaid
flowchart LR
    subgraph Interfaces
        CLI[CLI<br/>agentforge]
        API[HTTP API<br/>FastAPI]
        WEB[Dashboard<br/>Next.js]
    end
    WEB --> API
    CLI --> RT
    API --> SVC[Service<br/>background runs]
    SVC --> RT

    subgraph Core
        RT[Agent Runtime<br/>plan / act / observe / evaluate]
        PL[Planner]
        EX[Tool Executor]
        REG[Tool Registry]
        MEM[Memory]
        LLM[LLM Provider layer]
        EV[Evaluator]
    end
    RT --> PL
    RT --> LLM
    RT --> EX
    EX --> REG
    RT --> MEM
    RT --> EV
    EX --> SB[Sandbox<br/>local / docker]
    EV --> SB

    LLM --> P1[Anthropic]
    LLM --> P2[OpenAI-compatible<br/>OpenAI, OpenRouter,<br/>Gemini, local]
    LLM --> P3[Scripted]

    BE[Benchmark Engine] --> RT
    XP[Experiment Tracker] --> BE
    IL[Improvement Loop<br/>analysis, proposal, compare] --> BE
    GH[GitHub Integration] --> RT

    RT -- events --> OBS[Observers<br/>persistence, logs, SSE]
    OBS --> DB[(SQLite / PostgreSQL)]
```

| Component | Module | Responsibility |
|---|---|---|
| Domain models | `core/` | `AgentConfig`, `Run`, `Step`, `ToolCallRecord`, evaluation results, errors, IDs |
| LLM providers | `llm/` | Provider-neutral message types; adapters; pricing; registry/plugins |
| Runtime | `runtime/agent.py` | The execution loop, retries, limits, cancellation, events |
| Planner | `runtime/planner.py` | `react` (no upfront plan) and `plan_execute` strategies |
| Tools | `tools/` | `Tool` interface, registry with toolsets and entry-point plugins, safe executor, built-ins |
| Sandbox | `sandbox/` | Workspace path confinement; local process and hardened Docker execution |
| Memory | `memory/` | Short-term context compaction; persistent store interface (in-memory, SQL) |
| Evaluation | `evaluation/` | Evaluator interface + built-ins, aggregation, objective run metrics |
| Benchmarks | `benchmarks/` | Suite spec, repeated execution, statistics (Wilson CI, stddev) |
| Experiments | `experiments/` | Variants over a base config, comparison against a baseline |
| Improvement loop | `improvement/` | Failure analysis of benchmark runs, rule-based/manual proposals, applying them as new agent versions, re-benchmarking and comparison ([docs/improvement.md](docs/improvement.md)) |
| Reports | `benchmarks/report.py` | Publication records per benchmark run, stored under `<offline\|real>/` |
| Regression gate | `benchmarks/gate.py` | CI decision between a baseline and a candidate report: pass / regression / error with exit codes 0 / 1 / 2 and configurable thresholds ([docs/regression-gate.md](docs/regression-gate.md)) |
| Storage | `storage/` | Async SQLAlchemy tables and repositories; persistence observer |
| Service | `service.py` | Background execution of runs/benchmarks/experiments for the API |
| API | `api/` | REST + SSE endpoints, API-key auth |
| GitHub | `integrations/github/` | REST client, tools, issue → PR workflow |
| Observability | `observability/`, `runtime/events.py`, `api/routes/metrics.py` | Structured JSON logs, secret redaction, lifecycle events, OpenTelemetry export, Prometheus metrics |

## The agent loop

```
goal ─► recall memories ─► (plan) ─► ┌──────────────────────────────────────┐
                                     │ LLM call (retry w/ backoff)          │
                                     │ tool calls? ─yes─► execute each tool │──► observations
                                     │      │ no                            │      back to LLM
                                     │      ▼                               │
                                     │ final answer ─► evaluate             │
                                     │   passed / out of retries ─► finish  │
                                     │   failed & retries left ─► feedback ─┘
                                     └──────────────────────────────────────┘
limits: max_steps · timeout · max_tool_calls · consecutive tool-error cap · cancellation
```

- **Human approval gate** (`runtime/approval.py`, opt-in per agent via
  `AgentConfig.approval`): before executing a tool call whose permissions
  intersect `approval.require_for`, the runtime sets `run.status =
  awaiting_approval`, emits `tool.awaiting_approval` and blocks on an
  in-process `ApprovalGate` until an operator calls `POST
  /runs/{id}/approvals/{call_id}` (or, for `agentforge run`, a terminal
  prompt), the run is cancelled, or `approval.timeout_seconds` elapses (then
  the call is denied and the run continues). Denial fails only that tool
  call, not the run.
- Every run records `run_id`, status, timestamps, steps (with the LLM call
  record and all tool calls), errors, result, evaluation and metrics, plus the
  **config snapshot** and evaluator specs, so a run can be reproduced
  (`POST /runs/{id}/rerun`).
- **Status vs. success**: `status` describes execution (`succeeded` = the
  agent produced a final answer). Task success is `evaluation.passed`.
- Failed/timed-out runs are still evaluated (post-mortem) so benchmarks score
  them; cancelled runs are not.
- Retries: transient LLM errors (rate limits, 5xx, network) are retried per
  `RetryPolicy` with jittered exponential backoff; SDK-internal retries are
  disabled so attempt counts are accurate. `evaluation_retries` lets the agent
  continue with evaluator feedback after a failed check.

## Key design decisions

| Decision | Rationale |
|---|---|
| **Official SDKs as optional extras** (`anthropic`, `openai`), imported lazily inside adapters | Correct wire handling and typed errors without making the core depend on any vendor. |
| **One OpenAI-compatible adapter** serves OpenAI, OpenRouter, Gemini (its OpenAI-compatible endpoint) and local servers | Chat Completions is the common denominator; presets differ only in URL, key and token-parameter name. A native Gemini adapter is a planned enhancement. |
| **Opaque `ProviderPart`** in the neutral message format | Some APIs (e.g. Anthropic thinking blocks) require blocks to be echoed back verbatim; other providers drop them, keeping conversations portable. |
| **Runtime owns retries** | One source of truth for attempts, backoff and recorded retry metrics. |
| **Tool executor wraps every call** | Tools stay small; validation, permission policy, timeouts, truncation, redaction and records are uniform. |
| **Docker CLI (not SDK) for sandboxes** | No extra dependency; the argv is easy to audit and unit-test. |
| **SQLite default, PostgreSQL in compose** | Zero-config local use; same code via async SQLAlchemy. JSON columns for nested documents, real columns for filters/aggregates. |
| **Alembic migrations, applied automatically** | The API and CLI upgrade the schema on startup; a test asserts that migrations and ORM models never diverge (SQLite and PostgreSQL). |
| **In-process background execution** (asyncio tasks, semaphore) | Simple and reliable for a single node. Redis/worker queue deferred until multi-node execution is needed — Redis is intentionally *not* a dependency yet. |
| **Approval gate as in-process futures, not persisted state** | Consistent with in-process execution: a decision resumes the same run task directly. A server restart while a run is `awaiting_approval` loses the pause like any other in-flight run (`mark_interrupted` fails it), matching the existing single-node execution model. |
| **Lifecycle events + observers** | Persistence, logs, live SSE and OpenTelemetry export share one mechanism. |
| **Post-hoc trace export** | Spans are built from the finished run record with recorded timestamps: exact timings, zero overhead and no failure modes in the loop; live progress uses SSE. |
| **Prometheus text without a client library** | Metrics are derived from the database (survive restarts, include CLI runs); a few lines of formatting avoid a dependency. |
| **Lexical (BM25-style) memory search** | Dependency-free and deterministic; `MemoryStore.search` is the seam for a vector store. |
| **Benchmarks as normal runs** | Every benchmark attempt is a fully recorded run, inspectable in the same UI. Task/suite limits act as caps on the agent's own limits. |
| **Wilson score intervals** | Benchmark samples are small and pass rates near 0/1; comparisons show uncertainty rather than implying rankings. |
| **Scripted provider** | Deterministic, offline end-to-end tests and demos; explicitly not a model. |
| **Result class derived, never supplied** | `offline` (scripted) vs `real` is computed from the agent config; offline and real results are stored, reported and listed separately and cannot be compared. |
| **Immutable agent versions** | Every config change is a new snapshot; improvements and reverts add versions instead of rewriting history, so any benchmark can be traced to the exact config it ran. |
| **A gate error is never a pass** | The regression gate returns a separate `error` verdict (exit 2) when inputs are missing, invalid, not comparable or affected by infrastructure failures, so a CI pipeline cannot pass on data it could not evaluate. |
| **Deterministic, allowlisted proposals** | The built-in proposer is rule-based and cites evidence; all proposals may only touch an allowlist of config paths (no credentials, endpoints, sandbox or provider). |
| **argparse CLI** | No extra dependency for a modest command surface. |

## Trust boundaries

See `SECURITY.md`. In short: agent-generated commands are untrusted and run in
the sandbox with a scrubbed environment; secrets stay in the AgentForge
process; GitHub pushes are done by AgentForge, never by the agent; the local
sandbox is **not** a security boundary.

## Data model (tables)

`agents` · `agent_versions` (immutable config snapshots) · `runs` (config
snapshot, steps JSON, metrics, evaluation, labels) · `tool_calls`
(denormalised for analytics) · `memories` · `benchmark_runs` (suite snapshot,
results, summary, `agent_id`/`agent_version`, `result_class`) · `experiments` ·
`improvement_cycles` (analysis, proposal, applied changes, comparison).
