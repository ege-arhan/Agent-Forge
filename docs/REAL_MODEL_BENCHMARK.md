# Limited Real-Model Validation

> **Status (2026-09-27): NOT RUN — no real-model results exist.**
> `opencode.ai` is now reachable and `GET /zen/go/v1/models` lists all five
> models. One manual smoke request (outside this script) returned
> `HTTP 400 MissingSessionID`: OpenCode Go requires an `x-opencode-session`
> header, which AgentForge did not send. The provider now sends it (see
> *Provider requirements*). The experiment itself has not run; the Results
> section stays empty until it does.

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
| Provider | OpenCode Go (`provider: opencode-go`, the existing OpenAI-compatible provider with an `opencode-go` preset) |
| Endpoint | `https://opencode.ai/zen/go/v1` (no fallbacks) |
| Authentication | `--auth env` (key from `OPENCODE_API_KEY`) or `--auth proxy` (credential injected by an egress proxy); see below |
| Models (exact ids from `/models`) | `deepseek-v4.1-flash`, `mimo-v2.6-flash`, `muse-spark-1.3-contributor`, `glm-5.3-flash`, `kimi-k2.7-code` |
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

### Provider requirements (OpenCode Go)

From the OpenCode Go documentation (<https://opencode.ai/docs/go/>, checked
2026-09-27), implemented in the `opencode-go` preset:

- `x-opencode-session: <id>` on every model request. The id is the AgentForge
  run id: stable across all model calls (and retries) of one run, different
  for every run. Requests without it are rejected with `400 MissingSessionID`.
  It is an identifier, not a credential.
- `User-Agent: agentforge/<version>` instead of the SDK's generic user agent.
- Per-model endpoint: `muse-spark-1.3-contributor` is served on `/responses`
  (Responses API); the other four models on `/chat/completions`. Models that
  OpenCode serves on the Anthropic-format `/messages` endpoint are refused
  before any request. The `/models` listing carries no endpoint metadata, so
  the table in `agentforge/llm/openai_compat.py` is the source.

### Authentication modes

| Mode | Use | Behaviour |
|---|---|---|
| `--auth env` (default) | normal environments | reads `OPENCODE_API_KEY` and sends it as a bearer token; refuses to start without it |
| `--auth proxy` | Claude Cloud environments with an opencode.ai API Credential | an egress proxy adds the credential to requests to opencode.ai. `OPENCODE_API_KEY` is neither required nor read, and requests leave the process **without** an `Authorization` header; requires `HTTPS_PROXY` |

In both modes the key is never printed, logged or stored.

### Preflight (no model calls)

Before any task, `GET https://opencode.ai/zen/go/v1/models` checks that the
endpoint is reachable and which requested model ids it lists. Ids must match
the listing exactly; an unlisted model is a configuration failure and is never
called. **The listing is served without authentication, so it proves nothing
about the credential.** Authentication is established only by the first model
call; if that call is rejected with HTTP 401/403, the experiment stops
immediately (no further model calls) and the summary records
`authentication: FAILED`.

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
# Requirements: network access to opencode.ai, a Docker daemon, and either
# OPENCODE_API_KEY as an environment secret (never on the command line) or an
# egress proxy that injects the opencode.ai credential.
docker pull python:3.12-slim
uv run python scripts/real_model_validation.py               # --auth env
uv run python scripts/real_model_validation.py --auth proxy  # Claude Cloud API Credentials
```

The script stops after the plan above ("Stopped: the limited validation is
complete"), or earlier on an authentication failure (exit code 3). It never
runs the full suite, repeats, the improvement loop or statistics. After the run
it scans the stored results, the database and the log for credential-shaped
strings (bearer tokens, known key formats) and, when `OPENCODE_API_KEY` is set,
for the key itself, and reports "secret scan: clean" or fails.

## Limitations

- Three tasks per model at most, one run each: results describe these runs
  only. They do not support rankings, significance or general claims.
- Model availability and behaviour on OpenCode Go can change over time; the
  summary records the endpoint, commit and date.
- Token counts are whatever the endpoint reports; cost is not available.

## Infrastructure issues

- 2026-09-27 (earlier session): `opencode.ai` was denied by the cloud
  environment's network policy (HTTP 403 on CONNECT).
- 2026-09-27 (later): reachable. `GET /zen/go/v1/models` lists all five
  models. One manual chat-completions request to `deepseek-v4.1-flash` returned
  `HTTP 400 MissingSessionID` (no tokens, no result); fixed by sending
  `x-opencode-session` (see *Provider requirements*).
- The API key was provided in a chat message rather than as an environment
  secret. It was kept outside the repository for the session and deleted; it
  should be rotated and stored as `OPENCODE_API_KEY` in the environment's
  settings.
