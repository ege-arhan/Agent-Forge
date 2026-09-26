# Tasks

Status values: `todo`, `in-progress`, `done`, `blocked`. Keep entries honest:
only mark `done` when implemented, tested and documented.

## P0 — Critical

### T-014a CI green on GitHub
- **Status:** todo (workflows written; no run has appeared on GitHub yet —
  check that Actions are enabled for the repository)
- **Dependencies:** none
- **Description:** Verify `.github/workflows/ci.yml` and `security.yml` pass on
  GitHub runners (lint, mypy, tests on 3.12/3.13, PostgreSQL job, Docker
  sandbox job, image builds, pip-audit, gitleaks, CodeQL).
- **Implementation notes:** The API Dockerfile's apt layer, the dashboard
  image (Docker Hub rate limit) and GitHub-hosted actions could not be
  exercised in the development sandbox; everything else was verified locally
  (API image built without the apt layer and smoke-tested).
- **Tests:** CI itself.
- **Remaining work:** check the first CI run and fix failures.

## P1 — Important

### T-012 OpenTelemetry tracing and metrics
- **Status:** todo
- **Dependencies:** none
- **Description:** Optional `agentforge[otel]` extra with a `RunObserver` that
  emits spans (run → step → llm call / tool call) using GenAI semantic
  conventions; `/metrics` endpoint (Prometheus text) for run counts, durations,
  tool errors, tokens.
- **Tests:** in-memory span exporter assertions.

### T-014b Database migrations (Alembic)
- **Status:** todo
- **Dependencies:** none
- **Description:** Replace `create_all` with Alembic migrations (SQLite +
  PostgreSQL), `agentforge db upgrade`, migration test in CI.
- **Remaining work:** all. Until then schema changes require recreating the DB.

### T-013a API hardening
- **Status:** todo
- **Description:** request size limits, rate limiting, pagination caps
  everywhere, audit log of run creation; consider per-user tokens.

### T-013b Sandbox egress control
- **Status:** todo
- **Description:** Optional egress allowlist proxy for `network: bridge`
  sandboxes; document gVisor (`--runtime runsc`) option and add config field.

### T-009b Real-model benchmark results
- **Status:** blocked (needs API keys / budget approval from the owner)
- **Description:** Run `examples/experiments/model-comparison.yaml` with real
  providers and publish results with methodology in `docs/benchmarks.md`.

## P2 — Enhancements

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
- **Status:** todo — e.g. multi-file refactors, bug-fix suites with hidden
  tests, SWE-style tasks from real repositories (license-compatible).

### T-003b Streaming model output
- **Status:** todo — stream tokens to the SSE channel for live thoughts.

### T-004b Human approval for sensitive tools
- **Status:** todo — pause a run and wait for approval before tools with
  write/network permissions (policy per agent).

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
| T-010b | GitHub API + dashboard | `/github/status`, repo, issues, tasks (background workflow with pre-created run); Repositories and GitHub tasks pages; e2e tested with mocked GitHub + local bare remote |
