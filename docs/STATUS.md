# AgentForge Development Status

Date: 2026-09-26

Current milestone: 11 — Web dashboard (Milestones 0–10 core complete)

Latest work branch: `claude/focused-newton-j0z9l1` (no `main` branch exists
yet; see "Known issues").

Completed:
- M0 repository foundation (uv, ruff, mypy --strict, pytest, src layout, license)
- M1 core domain models and configuration
- M2 provider abstraction: Anthropic, OpenAI, OpenRouter, Gemini (OpenAI-compatible), local, scripted
- M3 agent runtime (retries, timeouts, cancellation, budgets, plan_execute, evaluation retries, events)
- M4 tool registry + executor + filesystem/terminal/git/http/github/memory tools
- M5 sandboxes (local, hardened Docker — verified against a real daemon)
- M6 memory (compaction, persistent memory, recall, tools)
- M7 evaluation engine and metrics
- M8 benchmark engine; M9 experiment tracking
- M10 GitHub client, tools and issue → draft PR workflow (CLI); API/dashboard pages pending
- HTTP API, CLI, Docker images, Compose, CI + security workflows, docs

Implemented:
- See CHANGELOG.md [Unreleased] and TASKS.md "Done".

Tests:
- 151 tests (unit, integration, e2e, docker); all passing locally.
- Coverage 89% (`uv run pytest --cov`).
- Integration + e2e suites also pass against PostgreSQL 16.
- Docker sandbox tests pass against Docker 29 (network isolation, read-only
  root, no capabilities, env isolation, timeouts, PID limit, full agent run).
- ruff, ruff format, mypy --strict: clean. pip-audit: no known vulnerabilities.

Known issues:
- CI workflows have not yet run on GitHub (T-014a).
- The Dockerfile apt layer could not be verified in the dev sandbox (Debian
  mirrors blocked); the rest of the image was built and smoke-tested.
- No `main` branch yet; work lives on the session branch.
- No database migrations; schema changes require recreating the DB (T-014b).
- No real-model benchmark results yet (needs API keys; T-009b).

Technical debt:
- Label-based run filtering (for GitHub tasks) not yet indexed.
- `service.py` runs work in-process (fine for one node).

Next priority:
- T-011 web dashboard, then T-010b GitHub API/dashboard, T-012 OpenTelemetry.

Project health:
- Green locally: lint, types, 151 tests, dependency audit.
