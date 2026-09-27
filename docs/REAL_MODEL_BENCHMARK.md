# Real-model benchmarks: LIMITED REAL-MODEL VALIDATION and improvement experiment

> **Status (2026-09-27).** Section 1: RUN — 10 task executions (5 models × 2
> tasks), all passed. Sections 3–9: the hard suite is built and validated
> OFFLINE; the real-model improvement experiment (sections 4–9) is **not run
> yet**. All REAL MODEL results use Provider: OpenCode Go. Small samples, one
> run per task: no rankings, no statistics.

OFFLINE RESULTS (scripted reference agents; they validate tasks and pipeline,
not any model) and REAL-MODEL RESULTS are stored and reported separately:
[`dogfood/results/offline/`](../dogfood/results/offline) and
[`dogfood/results/real/`](../dogfood/results/real). They are never combined or
compared.

## 1. Initial limited validation — REAL-MODEL RESULTS (Provider: OpenCode Go)

| Item | Value |
|---|---|
| Date | 2026-09-27, 01:33:10 – 01:36:12 UTC |
| AgentForge | 0.1.0, commit `6d4812b` (branch `claude/clever-bohr-woxzdb`) |
| Command | `scripts/real_model_validation.py --plan benchmark --sandbox docker` |
| Endpoint | `https://opencode.ai/zen/go/v1` (`/chat/completions`; Muse Spark: `/responses`) |
| Authentication | env (`OPENCODE_API_KEY`, process environment only) |
| Task executions | 10 of 10 allowed; sequential; each task once |
| Model calls | 59 in total (one per agent step); no retries (`llm_max_attempts: 1`, `evaluation_retries: 0`) |
| Sandbox | Docker `python:3.12-slim`, network none |
| Secret scan | clean (stored results, database, log) |
| Stored | `dogfood/results/real/limited-validation-20260927T013310Z/summary.{json,md}`; one report per task in `dogfood/results/real/dogfood-coding-v1/` and `dogfood-debugging-v1/`; run records in the harness database (`benchmark_runs.result_class = real`) |

Tasks (unchanged definitions, evaluators, prompts and limits, identical for every model):

- **Task 1 — coding/editing:** `dogfood-coding` v1 · `add-cli-flag`, agent
  `dogfood/agents/coding.yaml`. Checks: finished, words_unchanged,
  lines_option, help_documents_option, hidden_other_file.
- **Task 2 — debugging/testing/tool use:** `dogfood-debugging` v1 ·
  `pagination-off-by-one`, agent `dogfood/agents/debugging.yaml`. Checks:
  finished, tests_pass, hidden_edge_cases, tests_untouched, explains_cause.

Limits: max 20 steps, 600 s per task, 8000 max tokens per model call, token
budget 150 000 per task.

### Comparison

Latency is the mean wall time per model call over both tasks. Tokens are as
reported by the endpoint (input / output / total, both tasks).

| Model (exact id) | Coding | Debugging | Task success | Test success | Tool success | Avg steps | Avg latency per call | Tokens in / out / total | Cost |
|---|---|---|---|---|---|---|---|---|---|
| REAL MODEL · DeepSeek V4.1 Flash (`deepseek-v4.1-flash`) | pass | pass | 2/2 | 2/2 | 17/17 | 7.5 | 2196 ms | 30453 / 2367 / 32820 | NOT AVAILABLE |
| REAL MODEL · MiMo-V2.6-Flash (`mimo-v2.6-flash`) | pass | pass | 2/2 | 2/2 | 13/13 | 5.0 | 4602 ms | 17297 / 1573 / 18870 | NOT AVAILABLE |
| REAL MODEL · Muse Spark 1.3 Contributor (`muse-spark-1.3-contributor`) | pass | pass | 2/2 | 2/2 | 13/13 | 6.5 | 3403 ms | 28761 / 2939 / 31700 | NOT AVAILABLE |
| REAL MODEL · GLM-5.3 Flash (`glm-5.3-flash`) | pass | pass | 2/2 | 2/2 | 13/13 | 5.0 | 2101 ms | 16556 / 2041 / 18597 | NOT AVAILABLE |
| REAL MODEL · Kimi K2.7 Code (`kimi-k2.7-code`) | pass | pass | 2/2 | 2/2 | 13/13 | 5.5 | 2107 ms | 13186 / 1110 / 14296 | NOT AVAILABLE |

### Per-task details

All ten runs: status `succeeded`, evaluation score 1.0, all five checks
passed, 0 tool errors, 0 LLM retries, 0 evaluation retries, no timeout, no
step-limit hit, no token-budget hit, no provider error.

| Model | Task | Steps (= model calls) | Tool calls | Duration (s) | Avg latency per call (ms) | Tokens in / out / total | Cost |
|---|---|---|---|---|---|---|---|
| `deepseek-v4.1-flash` | add-cli-flag | 9 | 9 | 22.873 | 2243 | 18604 / 1445 / 20049 | NOT AVAILABLE |
| `deepseek-v4.1-flash` | pagination-off-by-one | 6 | 8 | 13.475 | 2126 | 11849 / 922 / 12771 | NOT AVAILABLE |
| `mimo-v2.6-flash` | add-cli-flag | 5 | 6 | 23.260 | 4320 | 8592 / 857 / 9449 | NOT AVAILABLE |
| `mimo-v2.6-flash` | pagination-off-by-one | 5 | 7 | 25.088 | 4884 | 8705 / 716 / 9421 | NOT AVAILABLE |
| `muse-spark-1.3-contributor` | add-cli-flag | 6 | 6 | 29.235 | 4564 | 13128 / 1765 / 14893 | NOT AVAILABLE |
| `muse-spark-1.3-contributor` | pagination-off-by-one | 7 | 7 | 17.505 | 2407 | 15633 / 1174 / 16807 | NOT AVAILABLE |
| `glm-5.3-flash` | add-cli-flag | 4 | 5 | 14.041 | 3118 | 6159 / 886 / 7045 | NOT AVAILABLE |
| `glm-5.3-flash` | pagination-off-by-one | 6 | 8 | 9.186 | 1422 | 10397 / 1155 / 11552 | NOT AVAILABLE |
| `kimi-k2.7-code` | add-cli-flag | 5 | 7 | 10.947 | 1856 | 5620 / 387 / 6007 | NOT AVAILABLE |
| `kimi-k2.7-code` | pagination-off-by-one | 6 | 6 | 14.531 | 2316 | 7566 / 723 / 8289 | NOT AVAILABLE |

### Failure analysis

No task failed, so there is nothing to classify. There were no provider, network,
infrastructure or configuration failures during the ten executions.

### Earlier calls (not part of the benchmark)

Two manual `deepseek-v4.1-flash` requests preceded the run: one
`HTTP 400 MissingSessionID` (before the session-header fix), one success
(37 input / 16 output tokens).

## 2. Benchmark limitations: why the first two tasks were too easy

All ten runs passed with score 1.0; every check passed in every run
(`add-cli-flag`: finished, words_unchanged, lines_option,
help_documents_option, hidden_other_file; `pagination-off-by-one`: finished,
tests_pass, hidden_edge_cases, tests_untouched, explains_cause). No run had a
tool error, a retry, a timeout or a limit hit.

What the tasks exercised: reading one short file, a small edit (an argparse
option; two one-line arithmetic fixes in a 10-line module), running a
command, and — for the debugging task — reading a failing assertion that
prints the wrong value. Resource use stayed far below the limits: at most 9
of 20 steps and 20 049 of 150 000 tokens per task.

What they did not differentiate:

- changes across several files, or a specification with many interacting
  rules;
- writing tests (neither task asked for tests), let alone tests that actually
  catch the bug;
- root causes that are not next to the symptom;
- preserving existing behaviour that no visible test covers;
- version-control workflows (history inspection, `git revert`);
- longer plans (no run needed more than 9 steps).

Why the improvement loop cannot be shown on them: the loop derives proposals
from failed runs. With every run passing, the failure analysis is empty, the
rule-based proposer has nothing to propose (`improve run` stops when all tasks
pass), and a comparison could only be "unchanged". The historical results in
section 1 are kept exactly as recorded.

## 3. Hard benchmark design — `dogfood-hard` v1 (OFFLINE-validated)

[`dogfood/benchmarks/hard.yaml`](../dogfood/benchmarks/hard.yaml): four new
tasks, standard library only, deterministic (fixed data; the git task builds
its history with fixed author/committer dates, so commit hashes are
reproducible). Each task has visible checks (what the agent is told), hidden
checks (edge cases and preserved behaviour it never sees) and process checks.
Suite caps: 25 steps, 900 s; the real agent's own limits (20 steps, 600 s)
are tighter and apply.

| Task | Capability | What makes it harder | Checks (visible · hidden · process) |
|---|---|---|---|
| `coupons-feature` | multi-file feature | new module + pricing + CLI + tests; six spec rules (case-insensitive codes, inclusive expiry, half-up rounding, fixed-discount cap, `min_subtotal`, tax on the discounted amount); unchanged output and result shape without a coupon | finished, unit_tests, existing_tests_untouched, coupon_tests_added · hidden_api, hidden_cli · ran_commands (optional) |
| `ledger-root-causes` | bug investigation + tests | symptom in the report, two independent root causes in the parser (naive comma split of quoted CSV amounts; float truncation of cents); one regression test **per cause** | finished, unit_tests, report_correct, existing_tests_kept, data_and_main_untouched · hidden_edge_cases, regression_test_per_root_cause (the agent's tests are run against three mutants: the original parser and each half-fixed parser, and must fail on all three) · names_both_causes (optional) |
| `git-regression-hunt` | tool-use workflow (shell + git) | six-commit history; commit 3 made `median` sort its input in place; must be found, undone with `git revert` (history kept, later commits kept), its hash recorded and committed, clean tree | finished, check_passes · bad_commit_identified, reverted_with_git_revert, history_preserved, later_changes_kept, record_committed, clean_worktree_on_main · used_shell |
| `env-overrides` | regression-sensitive change | "just read env vars" — but values must be converted like file values, empty and unknown `APP_*` variables ignored, precedence `DEFAULTS < file < env < overrides`, key mapping for `.`/`-`, and every documented file rule (e.g. ` #` comments vs `http://x/#frag`) preserved | finished, unit_tests, existing_tests_untouched, new_tests_added · hidden_existing_behaviour, hidden_env_rules · ran_commands (optional) |

Agent for the real experiment: [`dogfood/agents/engineer.yaml`](../dogfood/agents/engineer.yaml)
— the Coding Agent's system prompt, unchanged (not tuned to these tasks),
with filesystem, terminal and git tools.

### OFFLINE RESULTS — validation of the hard suite (scripted provider; says nothing about any model)

- Reference solutions ([`dogfood/agents/offline/engineer.yaml`](../dogfood/agents/offline/engineer.yaml)):
  **4/4 tasks pass** with score 1.0 (every check, including the optional ones),
  both in the local sandbox and in Docker (`python:3.12`, network none).
  Report: `dogfood/results/offline/dogfood-hard-v1/`.
- An agent that does nothing fails all four tasks
  (`tests/integration/test_improvement_loop.py`).
- Plausible wrong solutions fail exactly the check aimed at them
  (`tests/integration/test_hard_suite.py`): banker's rounding → `hidden_api`;
  an always-present `discount` key → `unit_tests` + `hidden_api`; one regression
  test for two causes → `regression_test_per_root_cause`; fixing only the CSV
  split → `report_correct`, `hidden_edge_cases`, `unit_tests`; a manual fix
  instead of `git revert` → `reverted_with_git_revert`; `git reset` →
  `history_preserved`, `later_changes_kept`, `bad_commit_identified`;
  unconverted env values → `hidden_env_rules`; treating every `#` as a comment →
  `hidden_existing_behaviour`.
- The run is stored like any benchmark (result class `offline`) and shown by
  the CLI (`bench report`) and the API (`/benchmarks/runs/{id}/report`,
  `/analysis`), which the dashboard uses.

## 4. Real-model improvement experiment — method

REAL MODEL · Provider: OpenCode Go · Model: `deepseek-v4.1-flash` (one model;
the purpose is to exercise the improvement loop, not to compare providers).

- Script: [`scripts/real_improvement_experiment.py`](../scripts/real_improvement_experiment.py).
- Tasks: `coupons-feature` and `ledger-root-causes`, chosen before any real run
  as the two with the most ways to fail (six interacting spec rules with hidden
  checks; two root causes with mutation-checked regression tests). The same two
  tasks for v1 and v2; the other two hard tasks are not run with a real model.
- Loop: agent v1 (stored version 1) → benchmark → failure analysis → proposal
  by the built-in rule-based proposer (derived only from v1's recorded
  failures) → agent v2 (stored version 2) → benchmark on the same suite
  snapshot → comparison. Stored in the AgentForge database; nothing is
  overwritten or deleted.
- Hard limits (enforced in code): at most **4 task executions** (2 × v1,
  2 × v2), sequential; `retry.llm_max_attempts: 1`, no evaluation retries;
  token budget 150 000 per task; proposed changes to the retry policy or the
  token budget are not applied. v2 does not run if v1 passes both tasks (then
  the tasks were still too easy and no improvement is claimed), if
  authentication fails, or if nothing applicable is proposed.
- Authentication: `--auth proxy` — the environment's API Credential is
  injected by the egress proxy; the key is not in the process, not in files.

## 5.–9. v1 results, failure analysis, proposal, v2 results, comparison

**Not run yet.**

## 10. Limitations

Initial validation (section 1):

- Two tasks per model, one run each: results describe these runs only. They
  do not support rankings, significance or general claims. Both tasks are
  small; all ten runs passed, so they do not separate the models.
- Durations and latencies depend on the endpoint's load at the time and
  include network time from the cloud environment.
- The `--plan benchmark` run skipped the smoke task and the model listing (the
  ids had been checked against `/models` beforehand); the `--plan validation`
  design described above has not been run.
- Model availability and behaviour on OpenCode Go can change over time; the
  summary records the endpoint, commit and date.
- Token counts are whatever the endpoint reports; cost is not available.

Improvement experiment (sections 4–9):

- One model, two tasks, one run per version: a before/after observation for
  this configuration, not evidence of a general improvement; the comparison's
  intervals cannot establish significance with one run per task.
- The rule-based proposer only changes configuration and prompt guidance.

## Appendix A — Validation design (section 1)

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

## Appendix B — Reproducing

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

## Appendix C — Infrastructure issues

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
