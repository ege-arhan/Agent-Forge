# AgentForge Development Status

Date: 2026-11-25

Version: **0.2.0** (released; tag `v0.2.0` on `main`). Milestones 0–15 are
merged. Milestone 16 (documentation and demo) and seven future-work items are
implemented in pull requests that await the owner's review; nothing has been
merged into `main` since 2026-11-01 (checked 2026-11-25). Earlier dated session reports are in
this file's git history.

## State of `main` (2026-11-25)

- `main` is at `9a0f8fb`. CI on its last push and the scheduled Security run
  of 2026-11-23 succeeded.

## This session (2026-11-25)

**PR #52** (branch `claude/stoic-gates-tpyw7k`), **stacked on PR #51** (the
branch is #51's head plus this work, so it holds every open agent change).
PRs #40–#51 were unchanged: #51's CI was green and its one review thread
(the unchanged-data check of `skip-dates`) is resolved; the others as
recorded below.

- Implemented T-017b, an optional model-assisted improvement proposer.
  `agentforge improve propose|run --proposer llm` and `POST /improvements`
  with `"proposer": "llm"` ask a model for the configuration changes; the
  rule-based proposer stays the default. New module
  `improvement/llm_proposer.py`; guide: `docs/improvement.md`,
  "Model-assisted proposals".
- Decisions worth the owner's eye:
  - The model is a server setting (`AGENTFORGE_IMPROVEMENT_PROPOSER_MODEL`,
    a JSON `ModelConfig`, unset by default). A request cannot name a model,
    endpoint or key.
  - The model is shown the agent's changeable settings and the analysis'
    categories, stages and signals — and **no text written by a run or an
    evaluator, and no task goals**. This keeps hidden checks out of prompts
    the model writes and keeps run output from instructing the proposer; it
    also means the model has less to go on than a person reading the
    evidence.
  - Its allowlist is narrower than the manual one: no `tools`, no
    `model.model`, no `retry.evaluation_retries`; the system prompt is
    append-only (1 200 characters per change, 8 changes).
  - A failed call or an answer without the JSON object is an error; there is
    no fallback to the rules and no retry.
- The answer is validated suggestion by suggestion; what fails is dropped
  with a note and the rest is kept. Found while testing: Pydantic reads
  `true` as 1 and `"400"` as 400 for a number, so a suggested
  `limits.max_steps: true` became a one-step limit and a string slipped past
  the suite cap. Booleans are now refused for non-boolean settings and values
  are recorded as the validated config holds them.
- No schema change: the proposal is stored as JSON; `proposer_call`
  (provider, model, usage, cost or `null`) is a new optional field.
- Scope, stated plainly: **no real model has produced a proposal with
  this.** Every test uses the scripted provider replaying an answer written
  for the test, so the tests show what happens to an answer, not whether a
  model's answers are any good, and the prompt is untuned. `TASKS.md` said
  this item was "only worth doing after real-model cycles show the
  rule-based proposals' limits"; that evidence still does not exist (T-009c,
  needs a budget), so the feature's value is unproven. The dashboard shows
  and applies such a proposal but cannot request one, and does not show the
  call's tokens.
- Verification on this branch: ruff, ruff format, mypy --strict: clean.
  `pytest -m "not docker"`: 639 passed (58 new: 52 unit in
  `tests/unit/test_llm_proposer.py`, 3 integration, 1 CLI, 2 API). Not run
  locally: PostgreSQL tests (no storage change), Docker-sandbox tests, the
  dashboard (untouched); CI runs them.

## Session of 2026-11-24

**PR #51** (branch `claude/stoic-gates-4w6htq`), **stacked on PR #50** (the branch is
#50's head plus this work, so it holds every open agent change). PRs #40–#50
were unchanged: #50's CI was green and its one review thread (the embedding
endpoint in the vector cache identity) is resolved; the others as recorded
below.

- Implemented the repository-with-issues part of T-008b: the dogfood suite
  `dogfood-swe` v1 (`dogfood/benchmarks/swe.yaml`). Three issues against one
  shared repository, `flowcal`, a calendar library written for the suite
  (six modules, 329 lines, a command line, a data file, 28 passing tests, a
  README that states the intended behaviour): `month-end-drift` (a bug whose
  cause exists at two sites), `conflict-report` (three causes in two
  modules) and `skip-dates` (a feature across five modules). The goal is the
  issue text. Checks: hidden tests that fail before and pass after, the
  repository's original tests read back from the first commit, the tests
  left in the workspace, and an unchanged data file. Design and
  limits: `dogfood/README.md`, "The repository suite".
- Offline reference solutions: `dogfood/agents/offline/swe.yaml`.
  `scripts/dogfood.py` has a `swe` role; for real runs it uses the existing
  `dogfood/agents/engineer.yaml`, unchanged, so the agent is not tuned to
  the suite. OFFLINE result recorded in
  `dogfood/results/offline/dogfood-swe-v1/` (3/3; this validates the tasks,
  not a model).
- No change to `src/`: the suite uses the existing benchmark format (a YAML
  anchor shares the repository between the tasks) and the existing
  evaluators.
- Scope, stated plainly: **no model has run this suite.** Whether it is
  harder for a model than `dogfood-hard`, or separates models at all, is
  unknown, and only a real run can tell (T-009c: needs credentials and the
  owner's budget approval). The repository is synthetic and small; tasks
  from real open-source repositories are not done. The real agent's limits
  (20 steps, 600 s) are tighter than the suite's (30 steps, 900 s) and
  apply, which may be what decides `skip-dates` rather than the task. The
  hidden checks hold the behaviour the issue and the README state; a
  correct solution with a different internal design should pass, but that
  has only been tried with the reference solutions and their variants.
- From the automated (Codex) review of PR #51, verified and fixed:
  `skip-dates` tells the agent not to change the shipped `calendar.json`,
  but no check held it, so an agent that tried the new command on that file
  and left the change behind still passed. The task now has the
  `data_untouched` check the bug tasks have; a regression test replays
  exactly that run and expects only this check to fail. The OFFLINE
  reference result was recorded again for the changed suite.
- Verification on this branch: ruff, ruff format, mypy --strict: clean.
  `pytest -m "not docker"`: 581 passed (12 new
  tests in `tests/integration/test_swe_suite.py`, and the existing
  reference/idle test now also runs for `swe.yaml`). The new tests show
  that the untouched repository passes its own tests and fails every hidden
  fix check, and that ten plausible wrong solutions fail exactly the
  intended checks (asserted as exact sets of failing checks). Not run: the
  suite in the Docker sandbox (Docker Hub answered 429 to the pull of
  `python:3.12`; the checks need `git` and `tar` in the image), PostgreSQL
  tests (no storage change), the dashboard (untouched).

## Session of 2026-11-23

**PR #50** (branch `claude/stoic-gates-yzktkz`), **stacked on
PR #49** (the branch is #49's head plus this work, so it holds every open
agent change). PRs #40–#49 were unchanged: #49's CI was green and it has no
review threads (its automated Codex review did not run: the reviewer reported
a usage limit); the others as recorded below.

- Implemented T-006b, vector memory search. An agent's `memory.search` is
  `lexical` (default, unchanged), `vector` (cosine similarity of embeddings)
  or `hybrid` (both rankings fused by reciprocal rank fusion), with
  `memory.min_similarity` as the threshold of the vector ranking; the run's
  automatic recall and the `recall` tool both use them. The embedder is a
  server setting (`AGENTFORGE_MEMORY_EMBEDDER`): `none`, `hashing` (built in,
  offline) or `openai-compatible` (an `/embeddings` endpoint over `httpx`; no
  new dependency). Vectors are cached per memory and embedder in the new
  `memory_embeddings` table (**migration 0004**), computed the first time a
  vector search sees a memory. New `agentforge memory list|search|add`.
  Guide: `docs/memory.md`.
- Decisions worth the owner's eye: the embedder is deliberately not part of
  an agent configuration, so a config submitted through the API cannot send
  memories or a key to an endpoint of its choosing; a missing or failing
  embedder makes the search fall back to lexical instead of failing the run;
  the two new settings are on the improvement loop's allowlist.
- Scope, stated plainly: the search is brute force in Python over an agent's
  1 000 most recent memories — no approximate index, no pgvector. The
  hashing embedder matches word forms ("configuring" / "configuration"), not
  meaning. **The `openai-compatible` embedder has never been run against a
  live endpoint** (mocked transport only; T-006c). `min_similarity` defaults
  to 0.0 and is not calibrated for any model, so vector search with the
  default returns weakly related memories too. Vectors left by a previous
  embedder are not cleaned up. Memories cannot be browsed through the API or
  the dashboard. No recall-quality measurement was made: there is no
  benchmark here that depends on memory.
- From the automated (Codex) review of PR #50, verified and fixed: the
  cached vectors of the `openai-compatible` embedder were keyed by model name
  only, so pointing the server at another endpoint that serves a different
  model under the same name would have compared new queries with the old
  endpoint's vectors (when the dimensions matched). The endpoint's host, port
  and path are now part of the embedder name; 2 tests added (566 passed).
- Verification on this branch: ruff, ruff format, mypy --strict,
  `ruff --select S`: clean. `pytest -m "not docker"`: 564 passed (50 new:
  42 unit, 5 storage, 1 CLI, 1 API, and the link check that runs for each
  documentation file now also runs for `docs/memory.md`; the allowlist
  assertions were added to an existing test). Integration and e2e tests against a local PostgreSQL 16:
  163 passed, including the migration/model drift check and a concurrent
  search test whose insert conflict was confirmed to occur on PostgreSQL.
  Docker-sandbox tests not run locally; CI runs them. Dashboard untouched
  (not rebuilt). The `agentforge memory` transcript in `docs/memory.md` is a
  real run with the hashing embedder (OFFLINE). Five deliberate breakages
  (threshold ignored, no lexical fallback, `recall` ignoring the mode, a
  resized stored vector reused, and one more that showed a redundant line,
  which was removed) were each tried against the new tests.

## Session of 2026-11-22

**PR #49** (branch `claude/stoic-gates-mx0wbn`), **stacked on
PR #48 and containing PR #47**: the branch is the head of #48 (the YAML
import, which contains #40–#46) with the head of #47 (the Next.js security
upgrade) merged in, because both this work and #47 change
`web/package-lock.json`. The merge conflicted only in this file; the stack's
version was kept. So this one branch holds every open agent change, with the
upgraded lockfile. PRs #40–#48 were unchanged: green CI, no unresolved
review findings (checked for #47 and #48 this session; the others as
recorded below).

- Implemented the last part of T-011b: component tests for the dashboard.
  Vitest 5 + React Testing Library + jsdom are new dev dependencies; 21
  tests in `web/tests/` render four pieces with the API client mocked:
  the agents page (list, empty and error states, creating from JSON and from
  YAML, broken and empty drafts, a rejected configuration, importing a file,
  a wrong file type), the runs page (ticking two runs to compare, the third
  tick replacing the oldest, the status filter, paging, unknown cost), the
  run page (a finished run, Approve and Deny at the approval gate, the live
  preview of streamed output and its reload on a recorded step, Re-run and
  *Compare with original*) and the *Activity over time* card (range buttons,
  unknown pricing, the error state).
- `npm test` now runs both suites: the 54 `node:test` unit tests of
  `web/lib` (`npm run test:unit`) and the component tests
  (`npm run test:components`). CI's dashboard job calls `npm test`, so it
  runs them without a workflow change.
- Scope, stated plainly: the tests mock the API client and `next/navigation`,
  so they check what a page renders and which API call a click makes, not
  the API itself or routing. Not covered: the run comparison page, the
  benchmark, experiment, improvement, repositories, GitHub and settings
  pages, the navigation, and anything visual (layout, themes). The tests
  found no bug in the dashboard; no application code changed.
- Verification on this branch: ruff, ruff format, mypy --strict: clean.
  `pytest -m "not docker"`: 514 passed. Docker-sandbox and PostgreSQL tests
  not run locally; CI runs both. Dashboard: lint, typecheck, 54 unit tests,
  21 component tests (run five times in a row, all passing), production
  build; a clean `npm ci` followed by `npm test` passes; `npm audit`: 0
  vulnerabilities with the new packages. Three deliberate breakages of the
  pages (parsing JSON through the API, Deny sending an approval, dropping
  the reload on a recorded step) each failed a test, then were reverted.
  The dashboard image build (`node:22-alpine`) was not run locally; CI
  builds it.

## Session of 2026-11-21

Two pull requests, on two branches, because the first is a security fix that
should not wait behind the stack.

**PR #47** (branch `claude/stoic-gates-op93zt`, **from `main`, independent of
every other PR — merge it first**). `npm audit` on `web/package-lock.json`
reported 11 advisories (1 critical, 3 high, 7 moderate), most in Next.js
16.3.6. No CI job audited npm packages and Dependabot did not watch `web/`,
so nothing had reported them. The PR upgrades Next.js to 16.4.6 and the
affected transitive packages (`npm audit`: 0), adds an `npm audit` job to the
Security workflow, adds `web/` to Dependabot and sets `agentRules: false`
(Next.js 16.4 otherwise writes `AGENTS.md`/`CLAUDE.md` into `web/`). Whether
each advisory was reachable in this dashboard was not assessed. Its own
`docs/STATUS.md` has the verification. **This branch and the rest of the
stack still carry the old lockfile.** The stack does not change
`web/package.json` or the lockfile, so merging it after #47 keeps the fix; a
trial merge of the two branches (2026-11-21) conflicted only in
`docs/STATUS.md`, where this file's version is the one to keep.

**YAML import PR** (branch `feature/agent-yaml-import`), **stacked on
PR #46** (merge #40 → #41 → #42 → #44 → #45 → #46 first; this branch
contains them). PRs #40–#46 were unchanged: green CI, no unresolved review
findings.

- Implemented the YAML-import part of T-011b. The dashboard's *New agent*
  form accepts YAML as well as JSON and can load a `.yaml`, `.yml` or
  `.json` file. JSON is parsed in the browser. YAML is sent to the new
  `POST /agents/parse`, which reads it with `yaml.safe_load` (as the CLI
  does), validates it against the agent schema and the server policy and
  returns it as JSON; nothing is stored until *Create agent*. No schema
  change.
- Security: the endpoint rejects YAML aliases. A "billion laughs" document
  of a few hundred bytes loads cheaply (aliases share one object) but is
  exponentially large once the response is serialised; a test sends one and
  expects a 400. Python object tags are refused by the safe loader (tested).
  The endpoint is behind the API key, the request-size limit and the rate
  limit like every other route (the API-key case is tested).
- Scope, stated plainly: comments and formatting of an imported file are not
  kept; only the agent form gained YAML (the experiment-variant and
  evaluator fields still take JSON); the CLI still accepts aliases.
- Verification on this branch: ruff, ruff format, mypy --strict: clean.
  `pytest -m "not docker"`: 514 passed (12 new). Docker-sandbox and
  PostgreSQL tests not run locally; CI runs both. Dashboard: lint,
  typecheck, 54 unit tests (7 new). Checked in a browser against a running
  API (dev server), 1440 px light and 420 px dark: importing
  `examples/agents/scripted-demo.yaml` and creating the agent; the messages
  for a wrong file type, broken YAML, a YAML alias, broken JSON and a
  duplicate name; no horizontal overflow; the only console errors were the
  expected 400 responses. No screenshot was added or regenerated.
- T-011b has one part left: component tests. Its recorded blocker (the
  `npm install vitest` crash) no longer reproduces — see TASKS.md.

## Session of 2026-11-20

**PR #46** (branch `claude/stoic-gates-8bmzax`), **stacked on PR #45**
(merge #40 → #41 → #42 → #44 → #45 first; this branch contains them).
PRs #40–#45 were unchanged: green CI, no unresolved review findings.

- Implemented the charts-over-time part of T-011b. New endpoint
  `GET /stats/timeseries?days=N` (1–90, default 30) returns one entry per
  UTC day — runs, succeeded, failed, evaluated, passed, tokens, known cost,
  runs with unknown pricing, mean duration — with empty days present. The
  dashboard home page shows them in an *Activity over time* card: four
  single-measure charts (runs, tokens, known cost, mean run duration), a
  7/14/30/90-day range, exact figures on hover and a table view. No schema
  change.
- Cost stays honest: a day whose runs have no known pricing has
  `known_cost_usd: null` and no bar; such runs are counted separately and
  never summed as zero (storage test and unit test cover this).
- Scope, stated plainly: days are UTC calendar days of a run's creation
  time (no local-timezone or weekly buckets); tokens, cost and duration
  count finished runs only; the rows of the range are aggregated in Python
  rather than in SQL (so SQLite and PostgreSQL agree on day boundaries),
  which is why the range is capped at 90 days; there is no breakdown by
  agent or model. The charts have been seen with OFFLINE (scripted) data
  only, whose tokens and cost are zero.
- Verification on this branch: ruff, ruff format, mypy --strict,
  `ruff --select S`: clean. `pytest`: 502 passed, 8 skipped (the
  Docker-sandbox tests: no `python:3.12-slim` image here). PostgreSQL tests
  not run locally; CI runs both. Dashboard: lint, typecheck, 47 unit tests
  (8 new) and production build pass. Checked in a browser against a running
  API: with the demo data, and with a scratch copy of it whose runs were
  spread over two weeks and given made-up costs and durations to exercise
  the bars, the hover figures and the unknown-pricing wording (that copy was
  discarded; nothing from it is committed). 1440 px, 1700 px and 420 px
  widths, light and dark, all four ranges; no console errors, no horizontal
  overflow. `scripts/screenshots.py` ran end to end;
  `docs/screenshots/dashboard-light.png` was regenerated from it and the
  other pictures were left as committed.
- T-011b now has two parts left: component tests (blocked on the npm/vitest
  resolver issue recorded in TASKS.md) and YAML import in the agent form.

## Session of 2026-11-19

**PR #45** (branch `claude/stoic-gates-6vxbc1`), **stacked on
PR #44** (merge #40 → #41 → #42 → #44 first; this branch contains them).
PRs #40–#44 were unchanged: green CI, no unresolved review findings.

- Implemented the run comparison view, a part of T-011b: the dashboard page
  `/runs/compare?a=RUN&b=RUN` shows two runs side by side — metrics with the
  difference B − A, evaluator results by name, the settings that differ
  between the two configuration snapshots, the tool calls paired step by
  step with the first row where the runs diverge, and both final answers.
  It is reached by ticking two runs in the run list or with *Compare with
  original* on a re-run. Dashboard only: no API, schema or Python change
  apart from the screenshot tooling and one test.
- Scope, stated plainly: steps are paired by position, so one extra step
  early in a run marks every later row as different (no re-alignment). Only
  tool calls, their outcomes and evaluation results are compared, not the
  model's text. A difference in cost or score is shown only when both values
  are known. The page states that two single runs are not a measured effect
  and warns when the runs have different goals or checks. It has been used
  on OFFLINE (scripted) runs only.
- From the automated (Codex) review of PR #45, verified and fixed: evaluators
  that share a name in one run (unnamed evaluators are named after their
  type) were collapsed into one row showing only the last result. They are
  now listed separately (`file_contains`, `file_contains #2`, matched by
  order); regression test added.
- Verification on this branch: ruff, ruff format, mypy --strict: clean.
  `pytest`: 501 passed, 8 skipped (the Docker-sandbox tests: no
  `python:3.12-slim` image here). PostgreSQL tests not run locally; CI runs
  both. Dashboard: lint, typecheck, 39 unit tests (13 new) and production
  build pass. Checked in a browser against a running API with the demo data:
  selecting runs (a third tick replaces the oldest), Compare, Swap,
  *Compare with original*, the empty and not-found states, 1440 px and
  420 px widths, light and dark; no console errors.
  `scripts/screenshots.py` ran end to end; `run-compare-light.png` is new
  and `runs-light.png` was regenerated (the list gained the tick column).
  The other pictures were left as committed.

## Session of 2026-11-18

**PR #44** (branch `claude/stoic-gates-hqwl3k`), **stacked on PR #42 and
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
- From the automated (Codex) review of PR #44, both verified and fixed: an
  OpenAI-compatible stream that closed cleanly before its final chunk was
  accepted as a complete answer (now a retryable `incomplete_stream` error);
  with `n > 1` the interleaved choices were concatenated (now only choice 0
  is read, as `complete()` does).

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
`ruff --select S`: clean. `pytest`: 501 passed, 8 skipped (the
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

**Merge #47 first** (the dashboard security fix; from `main`, independent).
Merge order for the rest: **#40 → #41 → #42 → #44 → #45 → #46 → #48 (YAML
import) → #49 (component tests) → #50 (vector memory) → #51
(`dogfood-swe` suite) → #52 (model-assisted proposer)** (each contains the
previous one; the last four also contain #47, so merging the last alone brings
in everything). Then close #13, #32, #33, #34, #37, #38 and
#39, whose commits are all in #40, and #43, whose commit is in #44. Do not
merge #43 by itself: it lacks the fixes above and conflicts with the stack.

Agent work is spread over twenty pull requests. The two oldest stacks could
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
- The model-assisted proposer has run against the scripted provider only; no
  real model has produced a proposal with it.
- The `agentforge-sandbox` image cannot be built in this development
  environment (Debian mirrors blocked); CI builds it.
- Databases created before migrations existed are rejected with a clear
  message; recreate them.
