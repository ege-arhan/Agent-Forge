# Limited Real-Model Validation

> **Status (2026-09-27): NOT RUN — no real-model results exist.**
> The development environment's network policy blocks `opencode.ai`, so the
> endpoint could not be reached (not even the model listing). No model was
> called and no result was recorded. Everything below describes the prepared
> method; the Results section stays empty until the experiment actually runs.

## 1. Offline / scripted results

Separate dataset, never combined with the section below:
[`dogfood/results/offline/`](../dogfood/results/offline) — scripted reference
agents on the dogfood suites. They validate the tasks and the pipeline, not
any model.

## 2. Real-model results

**None yet.** When the experiment runs, results are written to
`dogfood/results/real/limited-validation-<timestamp>/summary.{json,md}` plus one
report per task under `dogfood/results/real/<suite>-v<version>/`. Every row is
labelled `REAL MODEL`, `Provider: OpenCode Go`, and the model.

## Design

| Item | Value |
|---|---|
| Label | Limited Real-Model Validation (intentionally small; no statistics) |
| Provider | OpenCode Go (`provider: opencode-go`, the existing OpenAI-compatible provider with an `opencode-go` preset; key from `OPENCODE_API_KEY`) |
| Models | `opencode-go/deepseek-v4.1-flash`, `opencode-go/mimo-v2.6-flash`, `opencode-go/muse-spark-1.3-contributor`, `opencode-go/glm-5.3-flash`, `opencode-go/kimi-k2.7-code` |
| Smoke task (1 per model) | `starter` v1 · `create-greeting` (tool call `write_file`, file checks) |
| Task A (coding / editing) | `dogfood-coding` v1 · `add-cli-flag` (modify an existing CLI; visible + hidden checks) |
| Task B (tools + testing / debugging) | `dogfood-debugging` v1 · `pagination-off-by-one` (run tests, find two root causes, fix, re-run) |
| Maximum | 5 smoke + 10 benchmark = **15 task executions**, enforced in code |
| Order | sequential, one model at a time; a model's A/B tasks run only if its smoke task passed |
| Repeats / retries | each task once; `retry.llm_max_attempts: 1` (no model-call retries), no evaluation retries, failed tasks are not re-run |
| Agent configs | `dogfood/agents/coding.yaml` (smoke, A) and `debugging.yaml` (B), unchanged prompts and limits (max 20 steps, 8000 max tokens per call); only provider/model/endpoint are swapped, identically for every model |
| Resource guard | `limits.max_total_tokens: 150000` per task: a run that reaches it is stopped and recorded as "stopped by resource guard" |
| Sandbox | Docker, `python:3.12-slim`, no network (the three tasks need only Python) |
| Task definitions / evaluators | unchanged, identical for all models |

A task execution is one AgentForge run; each run makes several model calls
(one per step, bounded by the step limit and the token budget).

### Preflight (no model calls)

Before any task, `GET <endpoint>/models` verifies the key and which requested
model ids the endpoint lists. The ids are sent as listed (the `opencode-go/`
prefix is dropped when the endpoint lists the short id). An unlisted model is a
configuration failure and is never called. If `--base-url` is not given, the
candidates `https://opencode.ai/zen/go/v1` and `https://opencode.ai/zen/v1` are
tried in that order. **They could not be verified from this environment**;
the endpoint actually used is recorded in the summary.

### Measurements

Per task: success, test success (all `command` checks), evaluation score,
each check's result, tool calls, tool errors and tool success rate, steps, LLM
and evaluation retries, duration, input/output tokens (as reported by the
provider), timeout, step-limit hit, failure category and reason. Missing values
are written as "not available". Cost: no OpenCode Go pricing is configured and
AgentForge does not read billing, so estimated and actual cost are "not
available".

### Failure classification

Automatic, from the stored run record, then mapped to the experiment's
taxonomy: `setup`/`internal`/`cancelled` → infrastructure failure;
`llm_error` → provider/API failure; `timeout` → timeout; `step_limit` →
step-limit failure; `token_budget` → stopped by resource guard; `tool_errors`
→ tool execution failure; `tests_failed` → test failure; `workspace_state` →
coding failure; `wrong_output` → reasoning failure; `no_final_answer` →
planning failure; `process_not_followed` → tool selection failure; custom or
missing evaluations → evaluator failure. Unlisted models and authentication
errors → configuration failure. Provider and infrastructure problems are never
counted as model-quality failures. Finer distinctions (planning vs reasoning)
require reading the trace and are marked as such.

## Reproducing

```bash
# Requirements: OPENCODE_API_KEY as an environment secret (never on the
# command line), network access to opencode.ai, a Docker daemon.
docker pull python:3.12-slim
uv run python scripts/real_model_validation.py            # tries the candidate endpoints
uv run python scripts/real_model_validation.py --base-url https://<verified-endpoint>/v1
```

The script stops after the plan above ("Stopped: the limited validation is
complete"). It never runs the full suite, repeats, the improvement loop or
statistics. After the run it scans the stored results, the database and the log
for the key and reports "secret scan: clean" or fails.

## Limitations

- Three tasks per model at most, one run each: results describe these runs
  only. They do not support rankings, significance or general claims.
- Model availability and behaviour on OpenCode Go can change over time; the
  summary records the endpoint, commit and date.
- Token counts are whatever the endpoint reports; cost is not available.

## Infrastructure issues

- 2026-09-27: `opencode.ai` is denied by the cloud environment's network
  policy (HTTP 403 on CONNECT); the documentation site is also unreachable from
  this environment, so the endpoint URL could not be confirmed.
- The API key was provided in a chat message rather than as an environment
  secret. It was kept outside the repository for the session and deleted; it
  should be rotated and stored as `OPENCODE_API_KEY` in the environment's
  settings.
