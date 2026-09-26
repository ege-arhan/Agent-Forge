# Tasks

Status values: `todo`, `in-progress`, `done`, `blocked`. Keep entries honest:
only mark `done` when implemented, tested and documented.

## P0 — Critical

### T-011 Web dashboard (Milestone 11)
- **Status:** in-progress
- **Dependencies:** HTTP API (done)
- **Description:** Next.js + TypeScript + Tailwind dashboard in `web/`:
  overview (active runs, success/pass rates, recent runs, cost), agents list
  and detail, runs list and run detail (steps, thoughts, tool calls with
  arguments/outputs, errors, evaluation), benchmarks (suites, history, run
  detail), experiments (comparison table), settings (providers, tools,
  evaluators, API connection).
- **Implementation notes:** App Router, client-side fetching against
  `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`), optional API key
  stored in localStorage. Dense, developer-oriented UI; no marketing visuals.
- **Tests:** type check + lint + production build in CI; component smoke tests.
- **Remaining work:** everything (started after this file was written — see
  docs/STATUS.md for current state).

### T-014a CI green on GitHub
- **Status:** todo (workflows written; first run pending)
- **Dependencies:** none
- **Description:** Verify `.github/workflows/ci.yml` and `security.yml` pass on
  GitHub runners (lint, mypy, tests on 3.12/3.13, PostgreSQL job, Docker
  sandbox job, image builds, pip-audit, gitleaks, CodeQL).
- **Implementation notes:** The Dockerfile's apt layer and GitHub-hosted
  actions could not be exercised in the development sandbox (Debian mirrors
  and ghcr.io blocked there); everything else was verified locally.
- **Tests:** CI itself.
- **Remaining work:** check the first CI run and fix failures.

## P1 — Important

### T-010b GitHub integration: API + dashboard
- **Status:** todo
- **Dependencies:** T-011
- **Description:** Endpoints to inspect a repository, list issues, start an
  issue task (background `solve_issue`), list GitHub tasks (runs labelled
  `github_issue`); dashboard pages *Repositories* and *GitHub tasks*.
- **Implementation notes:** reuse `integrations/github/workflow.py`; run via
  `AgentForgeService`; store `pr_url` label; label filtering currently happens
  in Python — add an indexed column if it becomes hot.
- **Tests:** API tests with mocked GitHub + local bare remote (pattern in
  `tests/integration/test_github_workflow.py`).
- **Remaining work:** all.

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
