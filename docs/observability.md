# Observability

AgentForge exposes what agents do through four channels, all fed by the
runtime's lifecycle events (`runtime/events.py`).

## 1. Run records (source of truth)

Every run stores its steps, LLM call records (model, latency, attempts, stop
reason, tokens, estimated cost), tool calls (redacted arguments, status,
output, duration), errors, evaluation and metrics. Inspect them in the
dashboard (*Runs → run*), with `agentforge runs show <id> [--json]` or
`GET /api/v1/runs/{id}`.

## 2. Live events (SSE)

`GET /api/v1/runs/{id}/events` streams `run.started`, `plan.created`,
`step.started`, `llm.retry`, `llm.finished`, `tool.finished`,
`step.finished`, `evaluation.finished` and `run.finished` while the run is in
progress (keep-alive comments every 15 s; the stream ends after
`run.finished`).

## 3. Structured logs

`AGENTFORGE_LOG_JSON=true` emits one JSON object per line
(`ts`, `level`, `logger`, `msg`, plus fields such as `run_id`, `tool`,
`status`, `duration_ms`). Every log line passes through the secret redactor.
`AGENTFORGE_LOG_LEVEL` controls verbosity.

## 4. OpenTelemetry traces

Install the extra and enable export:

```bash
pip install 'agentforge[otel]'
export AGENTFORGE_OTEL_ENABLED=true
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # any OTLP/HTTP collector
agentforge serve    # or: agentforge run ...
```

Each finished run becomes one trace:

| Span | Key attributes |
|---|---|
| `agentforge.run` | `agentforge.run.id`, `agentforge.agent.name`, status, steps, tool calls, planner, sandbox, `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.*`, cost, evaluation passed/score, `agentforge.label.*` |
| `agentforge.step` | index, kind (plan/action/evaluation), evaluation result |
| `chat <model>` | `gen_ai.operation.name=chat`, `gen_ai.system`, `gen_ai.request.model`, finish reason, token usage, attempts, cost |
| `execute_tool <name>` | `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name`, `gen_ai.tool.call.id`, status, duration |

Spans are built from recorded timestamps after the run finishes: timings are
exact and tracing cannot slow down or break a run. Tool arguments and outputs
are deliberately not exported. Failed tool calls, LLM errors and failed runs
carry an error status.

## 5. Prometheus metrics

`GET /api/v1/metrics` (behind the API key when one is configured) returns
Prometheus text format:

| Metric | Type | Labels |
|---|---|---|
| `agentforge_info` | gauge | `version` |
| `agentforge_runs` | gauge | `status` |
| `agentforge_active_runs` | gauge | — |
| `agentforge_evaluated_runs`, `agentforge_evaluation_pass_ratio` | gauge | — |
| `agentforge_run_duration_seconds_{sum,count}` | summary | `status` |
| `agentforge_tool_calls` | gauge | `tool`, `status` |
| `agentforge_tokens` | gauge | `direction` |
| `agentforge_known_cost_usd`, `agentforge_runs_unknown_cost` | gauge | — |

Values are derived from the database, so they survive restarts and include
runs executed from the CLI against the same database.
