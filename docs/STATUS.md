# AgentForge Development Status

Date: 2026-09-27

Current milestone: 15 — Public beta (Milestones 0–14 complete; M15 in progress)

Stable branch: `main` (created at `7eb61d8`). All work arrives through pull
requests against `main`; see CLAUDE.md "Git workflow".

Latest work branch: `feature/real-model-validation` (stacked on
`feature/dogfooding-improvement-loop`, which is stacked on
`claude/focused-newton-j0z9l1`; merge in that order).

Open pull requests awaiting the owner:
- Workflow documentation (`claude/focused-newton-j0z9l1` → `main`).
- Dogfooding program + agent improvement loop
  (`feature/dogfooding-improvement-loop` → `main`, depends on the above).
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
models): **not run; no result exists.** Update (later on 2026-09-27):
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
- `service.py` executes work in-process (fine for one node).

Next priority:
- Owner actions above, then T-009b real-model dogfooding results and a real
  improvement cycle per agent.

Project health:
- Green locally across backend (SQLite, PostgreSQL, Docker) and dashboard.
