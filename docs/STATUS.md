# AgentForge Development Status

Date: 2026-11-18

Version: **0.2.0** (released; tag `v0.2.0` on `main`). Milestones 0–15 are
merged. Milestone 16 (documentation and demo) and four future-work items are
implemented in pull requests that await the owner's review; nothing has been
merged into `main` since 2026-11-01 (checked 2026-11-18). Earlier dated session reports are in
this file's git history.

## State of `main` (2026-11-18)

- `main` is at `9a0f8fb`. CI on its last push and the scheduled Security run
  of 2026-11-16 succeeded.

## This session (2026-11-18)

**PR #NN** (branch `claude/stoic-gates-hqwl3k`), **stacked on PR #42 and
containing PR #43** (merge #40 → #41 → #42 → this one, then close #43).
PRs #40–#42 were unchanged: green CI, no review findings.

PR #43 (streaming model output, T-003b, opened 2026-11-17 as a draft from
`main`) had green CI but had not been reviewed, conflicted with the #40–#42
stack in four documentation files, and its own `docs/STATUS.md` had gone back
to the pre-release text. This session merged it onto the stack, reviewed it
and fixed what the review found:

- **Anthropic stream errors were not translated.** The SDK sends the request
  when the stream is first read; a failure there (or midway) surfaced as a
  raw SDK exception instead of `LLMError`, so it was never retried. Fixed;
  tested through the real SDK over a mock transport (529 → retryable,
  401 → not).
- **Streams were never closed** after an error, a cancel or a timeout
  (leaked connections). `CompletionStream.aclose()` added; the runtime always
  calls it. A cancel request is now honoured between chunks.
- **Every token was written to the structured log** (`LoggingObserver` logs
  each event's data, and a delta's data is model text). `llm.delta` is now
  excluded from logging; it was already not persisted or traced.
- **Streaming was tied to a hard-coded list of provider names**, which
  excluded plugin providers and still listed `gemini` although the stack's
  native Gemini adapter does not stream. Removed: `model.stream` now always
  goes through `provider.stream()`, whose default answers without deltas.
- **One event per token.** Deltas are now coalesced (first chunk at once,
  then at most one event per 50 ms), because SSE subscriber queues are
  bounded and drop events when full.
- The OpenAI-compatible stream built its request separately from
  `complete()`; both now share one builder (a test asserts the bodies differ
  only by the two streaming fields). An empty stream is the same retryable
  error as an empty non-streamed response.
- The CLI left the cursor on the token line when a streamed call failed.

Added on top, to make the feature visible and testable end to end:

- The scripted provider replays a turn's text word by word when streaming is
  on (OFFLINE; for tests and demos only).
- Dashboard run page (the SSE part of T-011b): follows the run's event
  stream (fetch-based, because `EventSource` cannot send the API key), shows
  a *Model output (live)* preview and refreshes on record-changing events;
  the 1.5 s poll remains as a fallback.
- `docs/observability.md` documents streaming (PR #43 had no user
  documentation).

Scope, stated plainly: streaming is tested against the Anthropic and OpenAI
SDKs over mocked transports and end to end with the scripted provider; **it
has never been run against a live model** (no credentials). Only text is
streamed. The native Gemini adapter and Responses-API models do not stream.
A client that subscribes midway sees only later text.

Verification on this branch: ruff, ruff format, mypy --strict,
`ruff --select S`: clean. `pytest`: 499 passed, 8 skipped (the
Docker-sandbox tests: no `python:3.12-slim` image here). PostgreSQL tests
not run locally; CI runs both. Dashboard: lint, typecheck, 26 unit tests
(8 new) and production build pass. The live preview was checked in a browser
against a running API with a slowed-down scripted run: preview appears while
the step streams, clears when the step is recorded, no console errors.

## Session of 2026-11-16

**PR #42** (branch `claude/stoic-gates-h7ov06`), **stacked on
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

Merge order for everything open: **#40 → #41 → #42 → #NN**
(each contains the previous one), then close #13, #32, #33, #34, #37, #38 and
#39, whose commits are all in #40, and #43, whose commit is in #NN. Do not
merge #43 by itself: it lacks the fixes above and conflicts with the stack.

Agent work is spread over eleven pull requests. The two oldest stacks could
not both be merged until PR #40 combined them (2026-11-14):

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
- Streaming model output is tested with mocked transports and the scripted
  provider only; text only; no native streaming for Gemini or Responses-API
  models; no replay for clients that subscribe midway.
- The rule-based proposer changes configuration and prompt guidance only.
- The `agentforge-sandbox` image cannot be built in this development
  environment (Debian mirrors blocked); CI builds it.
- Databases created before migrations existed are rejected with a clear
  message; recreate them.
