# HTTP API

Base path `/api/v1`. Interactive OpenAPI docs are served at `/docs` when the
server runs (`agentforge serve`). When `AGENTFORGE_API_KEY` is set, every
endpoint except `/health` requires `Authorization: Bearer <key>`.

| Method & path | Description |
|---|---|
| `GET /health` | status, version, database connectivity (public) |
| `GET /stats?days=N` | run counts by status, active runs, completion and evaluation pass rates, mean score, tool call counts, known cost and number of runs with unknown cost, token totals |
| `GET /providers`, `GET /tools`, `GET /evaluators` | capabilities (tool schemas and permissions, evaluator parameter schemas) |
| `GET/POST /agents`, `GET/PUT/DELETE /agents/{id}` | stored agent configs (updates bump `version`) |
| `POST /runs` | start a run: `{goal, agent_id or config, evaluators?, labels?}` → 202 with the pending run |
| `GET /runs?status&agent_id&benchmark_run_id&limit&offset` | run summaries + total |
| `GET /runs/{id}` | full run record (steps, tool calls, evaluation, metrics, config snapshot) |
| `POST /runs/{id}/cancel` | cooperative cancel, then hard cancel after a grace period |
| `POST /runs/{id}/rerun` | reproduce with the stored config snapshot, goal and evaluators |
| `GET /runs/{id}/events` | server-sent events: `snapshot`, `run.started`, `plan.created`, `step.started`, `llm.retry`, `llm.finished`, `tool.finished`, `step.finished`, `evaluation.finished`, `run.finished` |
| `GET /benchmarks/suites[/{id}]` | suites discovered in `AGENTFORGE_BENCHMARKS_DIR` |
| `POST /benchmarks/runs` | `{suite_id, agent_id or config, repeats?, task_ids?}` |
| `GET /benchmarks/runs[/{id}]` | benchmark runs with results and summary |
| `POST /experiments` | `{name, suite_id, base_agent_id or base_config, variants, repeats?, task_ids?}` |
| `GET /experiments[/{id}]` | experiments; detail includes the comparison rows |
| `/github/...` | see [github.md](github.md) |

Errors: `404` unknown resources, `400` configuration/benchmark/workflow errors,
`409` conflicts (e.g. duplicate agent name), `422` request validation,
`401` missing/invalid API key, `502` upstream GitHub failures.
