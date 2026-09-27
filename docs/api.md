# HTTP API

Base path `/api/v1`. Interactive OpenAPI docs are served at `/docs` when the
server runs (`agentforge serve`). When `AGENTFORGE_API_KEY` is set, every
endpoint except `/health` requires `Authorization: Bearer <key>`.

| Method & path | Description |
|---|---|
| `GET /health` | status, version, database connectivity (public) |
| `GET /stats?days=N` | run counts by status, active runs, completion and evaluation pass rates, mean score, tool call counts, known cost and number of runs with unknown cost, token totals |
| `GET /providers`, `GET /tools`, `GET /evaluators` | capabilities (tool schemas and permissions, evaluator parameter schemas) |
| `GET/POST /agents`, `GET/PUT/DELETE /agents/{id}` | stored agent configs; `PUT ?change_summary=` stores a new version (a no-op when the config is unchanged) |
| `GET /agents/{id}/versions[/{version}]` | immutable version history, newest first (source, change summary, parent version, improvement id, config) |
| `POST /runs` | start a run: `{goal, agent_id or config, evaluators?, labels?}` → 202 with the pending run |
| `GET /runs?status&agent_id&benchmark_run_id&limit&offset` | run summaries + total |
| `GET /runs/{id}` | full run record (steps, tool calls, evaluation, metrics, config snapshot) |
| `POST /runs/{id}/cancel` | cooperative cancel, then hard cancel after a grace period |
| `POST /runs/{id}/rerun` | reproduce with the stored config snapshot, goal and evaluators |
| `GET /runs/{id}/events` | server-sent events: `snapshot`, `run.started`, `plan.created`, `step.started`, `llm.retry`, `llm.finished`, `tool.finished`, `step.finished`, `evaluation.finished`, `run.finished` |
| `GET /benchmarks/suites[/{id}]` | suites discovered in `AGENTFORGE_BENCHMARKS_DIR` (one or more directories separated by `:`; default `examples/benchmarks:dogfood/benchmarks`) |
| `POST /benchmarks/runs` | `{suite_id, agent_id or config, repeats?, task_ids?}`; with `agent_id` the run records the agent's current version |
| `GET /benchmarks/runs?suite_id&experiment_id&agent_id&result_class&limit` | benchmark runs with results, summary, `agent_id`, `agent_version` and `result_class` (`offline` or `real`) |
| `GET /benchmarks/runs/{id}` | one benchmark run |
| `GET /benchmarks/runs/{id}/analysis` | failure analysis: categories, per-task counts, failed runs with evidence, tool issues |
| `GET /benchmarks/runs/{id}/report` | publication record per task run (success, checks, tool calls, retries, duration, tokens or `null`, estimated cost, `actual_cost_usd: null`) |
| `GET /benchmarks/compare?baseline&candidate` | comparison (verdict, intervals, per-task changes); offline vs real is refused as `not_comparable` |
| `GET /benchmarks/gate?baseline&candidate[&max_pass_rate_drop&max_task_pass_rate_drop&max_mean_score_drop&min_pass_rate]` | CI regression gate result: `verdict` (`pass`/`regression`/`error`), `exit_code` (0/1/2), per-task counts, `errors`, `regressions`, `notes`; same rules as `agentforge bench gate` ([regression-gate.md](regression-gate.md)) |
| `POST /experiments` | `{name, suite_id, base_agent_id or base_config, variants, repeats?, task_ids?}` |
| `GET /experiments[/{id}]` | experiments; detail includes the comparison rows |
| `/github/...` | see [github.md](github.md) |

## Improvement loop

See [improvement.md](improvement.md) for the concepts.

| Method & path | Description |
|---|---|
| `GET /improvements/categories` | failure categories with descriptions |
| `POST /improvements` | `{benchmark_run_id, changes?, notes?}` → 201 cycle with analysis and proposal (rule-based unless `changes` is given; `changes` are `{path, value, operation?, rationale?}` limited to an allowlist) |
| `GET /improvements?agent_id&limit` | cycles, newest first |
| `GET /improvements/{id}` | one cycle |
| `POST /improvements/{id}/apply` | `{change_ids?}` → stores the next agent version (`source: improvement`) |
| `POST /improvements/{id}/evaluate` | 202; benchmarks the new version on the baseline's suite snapshot in the background, then records the comparison |
| `POST /improvements/{id}/reject` | `{reason?}`; after `apply`, the baseline config is restored as a new version (`source: revert`) |

Errors: `404` unknown resources, `400` configuration/benchmark/workflow errors,
`409` conflicts (e.g. duplicate agent name, an improvement action not valid in
the cycle's state, a disallowed change path), `422` request validation,
`401` missing/invalid API key, `502` upstream GitHub failures.
