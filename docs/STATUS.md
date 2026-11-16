# AgentForge Development Status

Date: 2026-11-16

Version: **0.2.0** (released; tag `v0.2.0` on `main`). Milestones 0–15 are
merged. Milestone 16 (documentation and demo) and three future-work items are
implemented in pull requests that await the owner's review; nothing has been
merged into `main` since 2026-11-01 (checked 2026-11-16). Earlier dated session reports are in
this file's git history.

## State of `main` (2026-11-16)

- `main` is at `9a0f8fb`. CI on its last push and the scheduled Security run
  of 2026-11-09 succeeded.

## This session (2026-11-16)

A new pull request from branch `claude/stoic-gates-h7ov06`, **stacked on
PR #41** (merge #40, then #41, then this one). PRs #40 and #41 were unchanged:
green CI, no review findings.

- Implemented T-020, trace-level failure diagnosis
  (`agentforge.improvement.diagnosis`, documented in `docs/improvement.md`).
  For each failed run it reads the recorded tool calls, plan and evaluator
  results and reports trace signals (e.g. `repeated_call`,
  `unverified_change`) and the stage they point to: planning, execution,
  verification, reasoning, reporting or undetermined. It appears in the
  failure analysis (API and stored cycles), `agentforge improve analyze`, the
  dashboard's agent improvement page and as notes on rule-based proposals.
  No database change.
- Scope, stated plainly: these are deterministic rules over tool-call
  records. The diagnosis does not read the model's text; `reasoning` is the
  residual when no process defect is found; a shell command is opaque to it
  (it may read, write or test). It has been exercised on unit-test traces and
  OFFLINE (scripted) benchmark runs only — whether the stages are useful on
  real-model failure traces is unverified (no credentials, no budget).
- Verification on this branch: ruff, ruff format, mypy --strict: clean.
  `pytest`: 461 passed, 8 skipped (the Docker-sandbox tests: no
  `python:3.12-slim` image here). PostgreSQL tests not run locally; CI runs
  both. Dashboard: lint, typecheck, 18 unit tests and production build pass;
  the agent improvement page was checked in a browser capture and
  `docs/screenshots/improvement-agent-light.png` regenerated from it.
  `scripts/tour.py` passes; the `improve analyze` transcript in
  `docs/tour.md` gained the new stage lines.

## Session of 2026-11-15

**PR #41** (branch `claude/stoic-gates-y0aicw`), **stacked on PR #40** (merge #40
first, then #41).
PR #40 itself was unchanged: green CI, no review findings, mergeable.

- Finished T-019b, the regression gate's remaining policies. All are opt-in;
  the defaults and existing verdicts are unchanged:
  - `--min-repeats N`: the gate cannot decide (exit 2) unless every task has
    at least `N` runs on both sides;
  - `--max-check-pass-rate-drop F`: per-check threshold, for a check that
    starts failing while its task still passes;
  - `--fail-on-category CATEGORY`: a candidate run failing with a listed
    failure category is a regression whatever the thresholds allow;
  - pooled baselines: repeat `--baseline` to compare against several accepted
    runs; every one must be comparable with the candidate.
  The same options exist on `GET /benchmarks/gate`.
- Bug found and fixed while doing so: the token budget compared totals, so
  reports with different numbers of repeats were compared unfairly (a
  candidate with three repeats looked like +200% tokens). Usage is now
  averaged per task first; regression test added.
- Scope, stated plainly: the pooled baseline is a rate over the reports the
  caller passes. The gate does not store accepted runs, weight them by age,
  detect drift or apply a significance test.
- Verification on this branch: ruff, ruff format, mypy --strict,
  `ruff --select S`: clean. `pytest`: 436 passed, 8 skipped (the
  Docker-sandbox tests: the `python:3.12-slim` image could not be pulled
  here). PostgreSQL tests not run locally; CI runs both. Dashboard (one type
  definition extended): lint, typecheck, unit tests and production build
  pass. The new options were also run by hand through the CLI on
  OFFLINE (scripted) benchmark runs.

## Pull requests awaiting the owner

Merge order for everything open: **#40 → #41 → the T-020 pull request**
(each contains the previous one), then close #13, #32, #33, #34, #37, #38 and
#39, whose commits are all in #40.

Agent work is spread over seven pull requests in two stacks. Before this
session the two stacks could not both be merged:

- **Milestone 16 stack** — #37 (offline tour) → #38 (screenshots, docs index,
  README) → #39 (walk-through recording, dashboard table fix). Green CI, no
  open review findings, merges cleanly into `main`.
- **Gemini / gate-budget stack** — #13 (native Gemini adapter, T-002b) → #32
  (gate token and latency budgets, T-019b part) → #33 → #34 (review fixes).
  Their CI was green when pushed in October, but all four now **conflict
  with `main`** (`CHANGELOG.md`, `docs/STATUS.md`) and with the milestone 16
  stack (also `ROADMAP.md`), so GitHub cannot merge them.

**PR #40 (branch `claude/stoic-gates-xe8k3q`) contains both stacks**
with the conflicts resolved (the head of #39 plus a merge of the head of
#34), and one fix on top (below). Two ways to merge:

1. Merge only #40, then close
   #13, #32, #33, #34, #37, #38 and #39 — their commits are all in it.
2. Or merge #37 → #38 → #39 first, then #40, and close #13, #32, #33 and #34.

Dependabot PRs #15–#19, #27–#31 and #36 are the owner's to merge; their CI
was not checked this session. #36 (Python 3.12 → 3.15 base image) is a
three-minor-version jump and deserves a deliberate look.

## Previous session (2026-11-14)

- Combined the two stacks as described above. Only documentation files
  conflicted; no source file needed manual resolution.
- Self-review of the Gemini adapter found and fixed:
  - tool schemas were sent in `parameters`, Gemini's restricted OpenAPI
    subset. Every built-in tool schema contains `additionalProperties`, and
    several contain `exclusiveMinimum`, which that subset does not define.
    They are now sent as `parametersJsonSchema` (standard JSON Schema);
  - an HTTP 200 body that is not a JSON object, and an error body that is
    not a JSON object, raised `ValueError`/`AttributeError` instead of a
    classified `LLMError`.
- **Not verified:** the Gemini adapter has never been run against the live
  API — there are no credentials in these sessions, and
  `ai.google.dev` is not reachable from them, so the field names above come
  from the API as the author knows it, not from a check made here. The tests
  use a mocked transport. Before relying on the adapter, run one real call
  with a tool (T-002c).

## Verification (2026-11-14, `claude/stoic-gates-xe8k3q`)

- ruff, ruff format, mypy --strict, `ruff --select S`: clean.
- `pytest`: 419 passed, 8 skipped — the skipped ones are the Docker-sandbox
  tests (a daemon ran here, but the `python:3.12-slim` image could not be
  pulled). Not run: PostgreSQL tests. CI runs both.
- Dashboard: lint, typecheck, unit tests and production build pass.
- The five new Gemini tests fail on the adapter as it was in #34 and pass
  with the fix.

## What 0.2.0 contains

- Runtime, providers (Anthropic, OpenAI-compatible incl. OpenCode Go, local,
  scripted), tools with guardrails, local and hardened Docker sandboxes,
  memory, evaluation, benchmarks, experiments, storage (SQLite/PostgreSQL,
  migrations 0001–0003), API, CLI, dashboard, GitHub issue → draft PR
  workflow, OpenTelemetry/Prometheus.
- Versioned agents and the improvement loop (analysis → proposal → new
  version → re-benchmark → comparison).
- Human approval gate for sensitive tools (T-004b).
- CI regression gate `agentforge bench gate` + `GET /benchmarks/gate` +
  GitHub Actions example (T-019).
- Dogfooding program: six agents, six suites (incl. `dogfood-hard`), OFFLINE
  reference solutions.

## Real-model validation (REAL, OpenCode Go) — final historical record

Documented in `docs/REAL_MODEL_BENCHMARK.md`; not rerun or altered.

- 5 models × 2 dogfood tasks: 10 executions, all passed (too easy to
  differentiate the models).
- `dogfood-hard`: `deepseek-v4.1-flash` passed the 2 tasks it ran (2 executions).
- Controlled improvement-loop demonstration: step limit 8 → failed at the
  limit; proposal `limits.max_steps` 8 → 25; v2 passed (2 executions);
  verdict `inconclusive`. A configuration-level change, not model learning.
- Totals: 14 task executions + 2 smoke calls, 107 model calls, 355 391
  tokens; cost NOT AVAILABLE. Small samples: no rankings, no significance.

## Owner actions

1. Merge the open agent pull requests (see above for the order).
2. Decide what comes after milestone 16 (ROADMAP "Future work").
3. Gemini: one live smoke call with `GEMINI_API_KEY` (T-002c).
4. Confirm branch protection on `main`; rotate the OpenCode Go key if not
   done; disable the old "Agent Forge" routine (T-018).

## Known limitations

- Real-model evidence is small (one run per task); see REAL_MODEL_BENCHMARK.md.
- The approval gate runs in-process (single-node execution model).
- The regression gate's pooled baseline is a plain rate over the reports it
  is given; it keeps no history of accepted runs and applies no significance
  test.
- The native Gemini adapter is tested with a mocked transport only (T-002c).
- The rule-based proposer changes configuration and prompt guidance only.
- The `agentforge-sandbox` image cannot be built in this development
  environment (Debian mirrors blocked); CI builds it.
- Databases created before migrations existed are rejected with a clear
  message; recreate them.
