# Tasks

Status values: `todo`, `in-progress`, `done`, `blocked`. Keep entries honest:
only mark `done` when implemented, tested and documented.

## P0 — Critical

_None open. Continue with P1 in roadmap order._

## P1 — Important

### T-015b Public beta readiness
- **Status:** todo
- **Dependencies:** none (T-013b, T-014c done)
- **Description:** end-to-end demo script/video instructions, getting-started
  walkthrough verified from a clean machine, docs review against actual
  behaviour, issue/PR templates, CONTRIBUTING.md, version 0.2.0 tag.

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
| T-014a | CI green on GitHub | CI (lint, mypy, tests 3.12/3.13, PostgreSQL, Docker sandbox, dashboard, image builds) and Security (pip-audit, ruff S, gitleaks, CodeQL) all passing |
| T-012 | OpenTelemetry + metrics | `agentforge[otel]`, run → step → chat/execute_tool spans with GenAI attributes from recorded timestamps (no args/outputs exported), `AGENTFORGE_OTEL_ENABLED`; `/api/v1/metrics` Prometheus text; tested with in-memory exporter |
| T-014b | Database migrations | Alembic env + initial revision, automatic upgrade in API/CLI, `db upgrade`/`db current`, legacy-DB detection, model/migration drift test on SQLite + PostgreSQL, packaged in wheel |
| T-014c | Release automation | tag-triggered workflow: version check, wheel/sdist, GHCR images (api/web/sandbox), draft GitHub release with CHANGELOG notes; `scripts/release_notes.py` + tests. PyPI publishing needs owner-configured trusted publisher |
| T-013b | Sandbox egress control | operator networks + `sandbox.proxy`, allowlisting egress proxy (stdlib, `python -m agentforge.sandbox.egress_proxy`), `sandbox.runtime` (gVisor), policy allowlists, Compose recipe; unit tests + real-Docker test (allowed host reachable, others 403, no direct route) |
| T-013a | API hardening | server policy for submitted configs/evaluators (credential exfiltration, SSRF, arbitrary imports, sandbox), body size limit, per-client rate limit, queue cap, security headers, audit log; 18 tests |
| T-010b | GitHub API + dashboard | `/github/status`, repo, issues, tasks (background workflow with pre-created run); Repositories and GitHub tasks pages; e2e tested with mocked GitHub + local bare remote |
