# Tasks

Status values: `todo`, `in-progress`, `done`, `blocked`. Keep entries honest:
only mark `done` when implemented, tested and documented.

## P0 — Critical

_None open. Continue with P1 in roadmap order._

## P1 — Important

### T-015b Public beta readiness / v0.2.0
- **Status:** in-progress — everything but the owner's GitHub actions is done.
- **Done:** CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue/PR templates,
  clean-clone walkthrough of the README quick start, stable `main` and the
  PR-based workflow, versions bumped to 0.2.0 everywhere
  (`scripts/release_notes.py check 0.2.0` passes), CHANGELOG `[0.2.0]` section,
  release readiness checklist (`docs/RELEASE_CHECKLIST.md`).
- **Remaining (owner, GitHub UI):** merge PRs #8 → #9 → #10 → #11; set `main`
  as default branch and protect it; push the `v0.2.0` tag on `main` (this
  builds artifacts, publishes GHCR images and drafts the release).

### T-018 Scheduled routine can access the repository
- **Status:** blocked (owner action in the routines UI)
- **Verified 2026-09-27:** two routines are enabled.
  - "AgentForge daily development" (daily 08:46 Europe/Istanbul): prompt
    updated this session — PR workflow, never merge/auto-merge/tag/publish,
    no real-model calls or experiments without written owner approval,
    feature freeze. It has **no repository source attached** (it tries
    `add_repo` at runtime); its last run left no PR, so repository access is
    unverified.
  - "Agent Forge" (daily 06:47 UTC): older prompt without the PR rules
    (its session produced PR #12). It was created through the HTTP API, so an
    agent cannot edit or disable it.
- **Owner:** disable "Agent Forge"; attach `ege-arhan/Agent-Forge` as a source
  of "AgentForge daily development"
  (https://claude.ai/code/routines/trig_01PkiuJ7LQqCzv7ZiFigY2DS).

## P2 — Enhancements (future work, not started)

### T-009c Broader real-model evaluations
- **Status:** todo — needs an owner budget. More tasks, repeats (`-r 3+`) and
  models on the dogfood and hard suites, so pass rates carry uncertainty
  estimates; a real improvement cycle on an unconstrained failure. The limited
  validation (T-009b) is the baseline for this.

### T-019b More regression policies
- **Status:** todo — e.g. per-check or per-category thresholds, token/latency
  budgets as gate criteria, trend baselines over several accepted runs,
  required repeats before a gate may pass.

### T-020 Richer failure analysis
- **Status:** todo — trace-level diagnosis (e.g. distinguishing planning from
  reasoning failures, which today needs a human reading the trace).


### T-002b Native Gemini adapter
- **Status:** todo — currently served by the OpenAI-compatible endpoint.

### T-011b Dashboard enhancements
- **Status:** todo
- **Description:** live trace via SSE instead of polling; component tests
  (React Testing Library once the npm/vitest resolver issue is resolved —
  `npm install vitest` currently crashes npm 10.9 with "Cannot read properties
  of null (reading 'edgesOut')"); YAML import in the agent form; run
  comparison view (two runs side by side); cost/time charts over time.
- **Tech debt:** ESLint pinned to 9.x because `eslint-plugin-react` (via
  `eslint-config-next` 16.3) fails on ESLint 10.

### T-006b Vector memory store
- **Status:** todo — implement `MemoryStore` with embeddings (pgvector or a
  local index) behind an optional extra.

### T-008b More benchmark suites
- **Status:** todo — e.g. multi-file refactors, larger bug-fix suites, SWE-style
  tasks from real repositories (license-compatible). The dogfood suites (v1,
  10 tasks) are small by design; grow them (new suite version) once real-model
  results show which tasks discriminate.

### T-017b LLM-assisted improvement proposals
- **Status:** todo — optional proposer that asks a model for changes, limited to
  the same path allowlist and server policy, with the rule-based proposer as
  default. Only worth doing after real-model cycles show the rule-based
  proposals' limits.

### T-003b Streaming model output
- **Status:** todo — stream tokens to the SSE channel for live thoughts.

### T-015 Distributed execution
- **Status:** todo — Redis-backed queue + worker process when multi-node
  execution is required.

## Done

| ID | Task | Notes |
|---|---|---|
| T-000 | Repository foundation | pyproject (uv, ruff, mypy strict, pytest), layout, .gitignore |
| T-001 | Core domain models | `core/config.py`, `core/models.py`, errors, IDs |
| T-002 | Provider abstraction | Anthropic + OpenAI-compatible (OpenAI/OpenRouter/Gemini/local) + scripted; pricing; plugin registry; tested with SDKs over mock transports |
| T-003 | Agent runtime | retries/backoff, timeouts, cancellation, max steps/tool calls, consecutive-error cap, refusal/max_tokens handling, plan_execute, evaluation retries, events |
| T-004 | Tool system | registry/toolsets/entry points, executor, filesystem/terminal/git/http/github/memory tools |
| T-005 | Sandbox | workspace confinement, local sandbox (scrubbed env, process-group kill, output caps), Docker sandbox (hardened, tested against a real daemon) |
| T-006 | Memory | lexical search, in-memory + SQL stores, context compaction, recall/persist in runtime, remember/recall tools |
| T-007 | Evaluation | 9 built-in evaluators, python custom evaluators, entry points, aggregation, objective metrics |
| T-008 | Benchmarks | YAML suites, setup (files/commands/git), allowed tools, repeats, concurrency, Wilson CI, storage |
| T-009 | Experiments | variants via deep-merge overrides, comparison with deltas, storage |
| T-010 | GitHub core | REST client (no merge), tools with repo allowlist, issue → branch → commit → push → draft PR workflow, CLI |
| T-API | HTTP API | agents, runs (create/list/get/cancel/rerun/SSE), stats, tools/providers/evaluators, benchmarks, experiments, API key |
| T-CLI | CLI | run, serve, bench, experiment, runs, agents, tools, providers, db, github |
| T-DOCKER | Containers | API image, sandbox image, Compose (+ sandbox override) |
| T-CI | CI/security workflows | written (see T-014a for verification) |
| T-011 | Web dashboard | Next.js 16 + TS + Tailwind 4; pages: dashboard, agents(+detail), runs(+detail trace), benchmarks(+detail), experiments(+detail), repositories, GitHub tasks, settings; light/dark; validated palette; lint/types/unit tests/build; screenshots in docs/screenshots |
| T-014a | CI green on GitHub | CI (lint, mypy, tests 3.12/3.13, PostgreSQL, Docker sandbox, dashboard, image builds) and Security (pip-audit, ruff S, gitleaks, CodeQL) all passing |
| T-012 | OpenTelemetry + metrics | `agentforge[otel]`, run → step → chat/execute_tool spans with GenAI attributes from recorded timestamps (no args/outputs exported), `AGENTFORGE_OTEL_ENABLED`; `/api/v1/metrics` Prometheus text; tested with in-memory exporter |
| T-014b | Database migrations | Alembic env + initial revision, automatic upgrade in API/CLI, `db upgrade`/`db current`, legacy-DB detection, model/migration drift test on SQLite + PostgreSQL, packaged in wheel |
| T-014c | Release automation | tag-triggered workflow: version check, wheel/sdist, GHCR images (api/web/sandbox), draft GitHub release with CHANGELOG notes; `scripts/release_notes.py` + tests. PyPI publishing needs owner-configured trusted publisher |
| T-013b | Sandbox egress control | operator networks + `sandbox.proxy`, allowlisting egress proxy (stdlib, `python -m agentforge.sandbox.egress_proxy`), `sandbox.runtime` (gVisor), policy allowlists, Compose recipe; unit tests + real-Docker test (allowed host reachable, others 403, no direct route) |
| T-013a | API hardening | server policy for submitted configs/evaluators (credential exfiltration, SSRF, arbitrary imports, sandbox), body size limit, per-client rate limit, queue cap, security headers, audit log; 18 tests |
| T-016 | Dogfooding program | `dogfood/`: 5 agents (coding, debugging, data analysis, security analysis, GitHub issue solver) with real-model and offline configs, 5 suites / 10 tasks with visible, hidden and process checks, `scripts/dogfood.py` (offline/real, credential check), reports per result class; tests prove every task is solvable by the reference agent and fails for an idle agent; OFFLINE results recorded; REAL not run (no credentials) |
| T-017 | Agent improvement loop | migration 0002 (agent versions, improvement cycles, benchmark provenance + result class), failure analysis, rule-based/manual proposals with path allowlist, apply → new version, evaluate on the baseline suite snapshot, comparison with Wilson verdicts, reject/revert as a new version; CLI, API, dashboard Improvement pages; unit/integration/e2e tests on SQLite and PostgreSQL |
| T-010b | GitHub API + dashboard | `/github/status`, repo, issues, tasks (background workflow with pre-created run); Repositories and GitHub tasks pages; e2e tested with mocked GitHub + local bare remote |
| T-004b | Human approval for sensitive tools | Opt-in per agent (`AgentConfig.approval.require_for`/`timeout_seconds`); runtime pauses (`RunStatus.AWAITING_APPROVAL`) before a tool call needing one of the listed permissions and blocks on an in-process `ApprovalGate` until decided, cancelled or timed out (then denied); denial fails only that call, not the run. `GET/POST /runs/{id}/approvals[/{call_id}]`; dashboard run page shows a Pending approval card with Approve/Deny; `agentforge run` prompts on a TTY and auto-denies without one. Migration 0003 (written as 0002 on its branch; renumbered after the stack's 0002) widens `runs.status` (`String(16)` → `String(24)`, "awaiting_approval" didn't fit — caught by testing against real PostgreSQL, not just SQLite). Unit + e2e (API, real Postgres) + a regression test for a synchronous-decide race found during manual dashboard verification (screenshots: paused run + Approve card, and the resumed/succeeded run) |
| T-009b | Limited real-model validation | OpenCode Go provider fixes (`x-opencode-session`, Responses API routing, proxy-injected credentials); 5 models × 2 dogfood tasks (10 executions, all passed); hard suite `dogfood-hard` v1 (4 tasks, offline-validated; 2 run with `deepseek-v4.1-flash`, both passed); controlled improvement-loop demonstration (step limit 8 → failed, proposal `max_steps` 25 → v2 passed; verdict inconclusive). REAL results in `dogfood/results/real/`, write-up in `docs/REAL_MODEL_BENCHMARK.md`. Small samples: no rankings; not evidence of model learning |
| T-019 | CI regression gate | `agentforge bench gate` (exit 0 pass / 1 regression / 2 cannot decide), thresholds, report `suite_digest` + `failure_category`, `GET /benchmarks/gate`, dashboard verdict on evaluated cycles, GitHub Actions example with a committed offline baseline, `docs/regression-gate.md`; unit, CLI e2e and API tests |
