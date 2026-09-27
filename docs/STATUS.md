# AgentForge Development Status

Date: 2026-09-27

Current milestone: 15 — Public beta (Milestones 0–14 complete; M15 in progress)

Stable branch: `main` (created at `7eb61d8`). All work arrives through pull
requests against `main`; see CLAUDE.md "Git workflow".

Latest work branch: `claude/clever-bohr-woxzdb` (PR #11), stacked on
`feature/real-model-validation` (#10) → `feature/dogfooding-improvement-loop`
(#9) → `claude/focused-newton-j0z9l1` (#8); merge #8, #9, #10, #11 in that
order.

Also completed (PR #12, merged into this branch):
- **T-004b Human approval for sensitive tools** (P2, now done): opt-in per
  agent (`AgentConfig.approval.require_for` permissions,
  `approval.timeout_seconds`); the runtime pauses a run
  (`RunStatus.AWAITING_APPROVAL`) before a tool call needing one of the listed
  permissions, blocking on an in-process `ApprovalGate` until an operator
  decides via `GET/POST /runs/{id}/approvals[/{call_id}]`, the run is
  cancelled, or the timeout elapses (denied by default; denial fails only
  that tool call, not the run). `agentforge run` (in-process) prompts on a
  TTY and auto-denies without one, so it can never hang a non-interactive
  invocation. Dashboard run page shows a "Pending approval" card with
  Approve/Deny.
  - Migration `0003` (numbered `0002` on PR #12; renumbered after the
    stack's `0002`) widens `runs.status` from `String(16)` to `String(24)`:
    `"awaiting_approval"` (17 chars) didn't fit the original column. Caught by
    running the migration-drift test and the full e2e suite against a real
    PostgreSQL 16 instance, not just the SQLite default (SQLite doesn't
    enforce `VARCHAR` length, so this would have shipped silently broken for
    Postgres deployments).
  - A synchronous-decide race (an observer deciding while handling the same
    `tool.awaiting_approval` event the gate is about to wait on — the
    non-interactive CLI's auto-deny) was found by manually running
    `agentforge run` end-to-end, not by the automated tests: the run blocked
    for the full timeout instead of returning immediately. Fixed by splitting
    `ApprovalGate.request` into a synchronous `begin()` (register) called
    before the event is emitted and an async `wait()` called after; added a
    regression test.
  - Manually verified against the real dashboard: started the API and web dev
    servers, created a run through the API with `approval.require_for:
    [fs:write]`, confirmed the run paused with a working "Pending approval"
    card (screenshotted), clicked Approve in a real headless-Chromium
    session, and confirmed the run resumed and succeeded.


Open pull requests awaiting the owner:
- #8 Workflow documentation (`claude/focused-newton-j0z9l1` → `main`).
- #9 Dogfooding program + agent improvement loop (depends on #8).
- #10 Limited Real-Model Validation preparation (depends on #9).
- #11 OpenCode Go session fix, REAL results, hard suite, improvement
  experiment and controlled demonstration (depends on #10).
- #12 Human approval gate for sensitive tools (T-004b), from another session,
  based on `main` and independent of the stack. A trial merge with #11
  conflicts in CHANGELOG.md, ROADMAP.md, docs/STATUS.md,
  `api/schemas.py` and `web/lib/api.ts`: whichever lands second must merge
  `main` and resolve them.
- Dependabot PRs #1–#7 target the old session branch; the owner should close
  or retarget them to `main`.

Completed in this session:
- T-016 dogfooding program: `dogfood/` with five agents (coding, debugging,
  data analysis, security analysis, GitHub issue solver), each with a
  real-model config, an offline reference agent and a benchmark suite
  (10 tasks with visible, hidden and process checks); `scripts/dogfood.py`
  with separate `offline` and `real` modes.
- T-017 agent improvement loop: immutable agent versions, benchmark
  provenance and result class (migration `0002`), failure analysis,
  rule-based/manual proposals limited to an allowlist, apply as a new version,
  re-benchmark on the baseline's suite snapshot, comparison with Wilson
  intervals and verdicts, reject/revert; CLI (`agentforge improve …`,
  `bench report`, `bench compare`), API (`/improvements`,
  `/benchmarks/runs/{id}/analysis|report`, `/benchmarks/compare`,
  `/agents/{id}/versions`) and dashboard pages (Improvement, per-agent view).
- Review fixes: concurrent agent updates now allocate distinct versions
  (row lock; reproduced on PostgreSQL first), and benchmark runs take the
  config and recorded version from one stored-agent snapshot.
- Benchmark-design fix found while dogfooding: a run stopped by its step limit
  counted as passed when the workspace happened to satisfy the checks. The
  dogfood suites now require `completed` (the starter suite is unchanged).

Limited Real-Model Validation (2026-09-27, owner request, five OpenCode Go
models): **run on 2026-09-27** (`--plan benchmark`, commit `6d4812b`):
5 models × 2 existing tasks (`add-cli-flag`, `pagination-off-by-one`), 10 task
executions, 59 model calls, no retries, Docker sandbox. All 10 passed (score
1.0, 0 tool errors); cost NOT AVAILABLE; secret scan clean. REAL results in
`dogfood/results/real/`, write-up in `docs/REAL_MODEL_BENCHMARK.md` (small
sample, no ranking). Because every run passed, the hard suite
`dogfood-hard` v1 was added (4 tasks, OFFLINE: reference 4/4, idle 0/4, wrong
solutions rejected by the intended checks) together with a limited real
improvement experiment (one model, two tasks, ≤ 4 executions). **Run
2026-09-27** (commit `f8ae4e4`, proxy-injected credential): `deepseek-v4.1-flash`
v1 passed both `coupons-feature` and `ledger-root-causes` with every hidden
check, so no improvement was proposed, v2 was not run and no improvement is
claimed (2 task executions, 28 model calls). The hard suite is still too easy
for this model. **Controlled demonstration** (commit `0bda883`, 2 executions):
the same agent with a documented `limits.max_steps: 8` failed
`ledger-root-causes` at the step limit; the loop proposed `max_steps 8 → 25`
(the only change) and v2 passed the unchanged task in 10 steps; comparison
`inconclusive` (one run each). Not evidence of model learning. Earlier the same day:
`opencode.ai` is reachable and `GET /zen/go/v1/models` lists all five models.
One manual smoke request returned `HTTP 400 MissingSessionID` (no tokens, no
result). Fixed on `claude/clever-bohr-woxzdb` (stacked on
`feature/real-model-validation`): the `opencode-go` preset sends
`x-opencode-session` (the run id) and an `agentforge/<version>` user agent,
routes `/responses` models (Muse Spark) through the Responses API, and the
script gains `--auth proxy` for proxy-injected credentials. Prepared on
`feature/real-model-validation` (stacked on the improvement-loop PR): the
`opencode-go` provider preset, an optional per-run token budget, the harness
`scripts/real_model_validation.py` and `docs/REAL_MODEL_BENCHMARK.md`.
Owner actions: allow `opencode.ai` in the environment's network settings,
store the key as `OPENCODE_API_KEY` (and rotate the key that was pasted into
chat), confirm the OpenCode Go endpoint URL.

Results:
- OFFLINE / SCRIPTED PROVIDER (validates tasks and pipeline, not a model):
  all 10 dogfood tasks pass with the reference agents (local sandbox); 8/8
  non-git tasks also pass in the hardened Docker sandbox (`python:3.12-slim`,
  no network); an idle agent fails every task. Improvement-loop demo:
  `dogfood-demo-coder` v1 0/6 → proposal `limits.max_steps: 3 → 20` → v2 6/6
  (verdict "improved"; deterministic replay, mechanics only). Reports:
  `dogfood/results/offline/`.
- REAL MODEL PROVIDER: **not run.** No provider credentials and no local model
  server in the development environment; `scripts/dogfood.py real` refuses to
  run and recorded nothing. No real-model numbers exist.

Tests (2026-09-26, this branch):
- Python: 265 tests passing (unit, integration, e2e, 8 Docker-sandbox tests
  with a running daemon); integration + e2e (79) also pass against
  PostgreSQL 16, including the migration drift check and the `0002` backfill.
- Dashboard: ESLint, `tsc --noEmit`, 16 unit tests (node:test), production
  build; Improvement pages checked in Chromium (light and dark).
- ruff, ruff format, mypy --strict clean; `ruff --select S` clean;
  pip-audit and `npm audit --omit=dev`: no known vulnerabilities; gitleaks on
  the working tree flags only Next.js build output (`web/.next`, gitignored).

Scheduled routine (inspected 2026-09-26) — autonomous development is **not**
reliably working yet:
- "AgentForge daily development" (daily 08:46 Europe/Istanbul) has no
  repository source and no connectors: its sessions start without a checkout
  and cannot push or open pull requests.
- An older routine, "Agent Forge" (daily 06:47 UTC), still runs with an
  outdated prompt (predates the `main`/PR workflow) and without a GitHub
  connector, duplicating the daily session.
- Owner actions: see DEVELOPMENT.md "Scheduled autonomous sessions" (attach
  `ege-arhan/Agent-Forge` to the daily routine; disable the old routine;
  optionally add a provider key for real-model dogfooding). Tracked as T-018.

Other owner actions:
- Set `main` as the default branch and protect it.
- Decide on an API budget for real-model dogfooding (T-009b).
- No release tag and no v0.2.0 until real results exist (owner's instruction).

Known issues / limitations:
- The `agentforge-sandbox` image cannot be built in the development
  environment (Debian mirrors blocked); CI builds it. `dogfood-issues` was
  verified with the local sandbox only.
- The rule-based proposer changes configuration and prompt guidance only; an
  LLM-assisted proposer is a P2 idea (T-017b).
- Databases created before migrations existed are rejected with a clear
  message; recreate them.

Technical debt:
- ESLint pinned to 9.x (eslint-plugin-react incompatible with ESLint 10).
- Vitest cannot be installed with npm 10.9 (resolver crash); web unit tests
  use node:test with type stripping.
- `service.py` executes work in-process (fine for one node); the approval
  gate follows the same model (in-process futures, not persisted — a server
  restart while a run is `awaiting_approval` fails it, like any other
  in-flight run).

Next priority:
- Owner actions above, then T-009b real-model dogfooding results and a real
  improvement cycle per agent.

Project health:
- Green locally across backend (SQLite, PostgreSQL, Docker) and dashboard.
