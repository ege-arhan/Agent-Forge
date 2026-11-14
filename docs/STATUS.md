# AgentForge Development Status

Date: 2026-11-14

Version: **0.2.0** (released; tag `v0.2.0` on `main`). Milestones 0–15 are
merged. Milestone 16 (documentation and demo) and two future-work items are
implemented in pull requests that await the owner's review; nothing has been
merged into `main` since 2026-11-01. Earlier dated session reports are in
this file's git history.

## State of `main` (2026-11-14)

- `main` is at `9a0f8fb`. CI on its last push and the scheduled Security run
  of 2026-11-09 succeeded.

## Pull requests awaiting the owner

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

## This session (2026-11-14)

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
- The regression gate compares against one baseline; trend baselines,
  per-check thresholds and required repeats are future work (T-019b).
- The native Gemini adapter is tested with a mocked transport only (T-002c).
- The rule-based proposer changes configuration and prompt guidance only.
- The `agentforge-sandbox` image cannot be built in this development
  environment (Debian mirrors blocked); CI builds it.
- Databases created before migrations existed are rejected with a clear
  message; recreate them.
