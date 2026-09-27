# AgentForge Development Status

Date: 2026-09-26

Current milestone: 15 — Public beta (Milestones 0–14 complete)

Stable branch: `main` (created at `7eb61d8`, the last commit with green CI
and all 198 tests passing locally). All further work arrives through pull
requests against `main`; see CLAUDE.md "Git workflow".

Open pull requests: the workflow-documentation PR from
`claude/focused-newton-j0z9l1`; Dependabot PRs #1–#7 (they target the old
session branch and should be closed or retargeted to `main` by the owner).

Completed:
- M0 repository foundation (uv, ruff, mypy --strict, pytest, src layout, Apache-2.0)
- M1 core domain models and configuration
- M2 providers: Anthropic, OpenAI, OpenRouter, Gemini (OpenAI-compatible), local, scripted
- M3 agent runtime (retries, timeouts, cancellation, budgets, plan_execute, evaluation retries, events)
- M4 tool registry + executor + filesystem/terminal/git/http/github/memory tools
- M5 sandboxes (local; hardened Docker verified against a real daemon)
- M6 memory; M7 evaluation; M8 benchmarks; M9 experiments
- M10 GitHub: client, tools, issue → draft PR workflow via CLI, API and dashboard
- M11 web dashboard (Next.js 16, TypeScript, Tailwind 4), light/dark
- HTTP API, CLI, Docker images, Compose, CI + security workflows, docs

Implemented:
- See CHANGELOG.md [Unreleased] and TASKS.md "Done".

Tests:
- Python: 198 tests (unit, integration, e2e, docker) passing.
- Integration + e2e also pass against PostgreSQL 16.
- Docker sandbox tests pass against Docker 29.
- Dashboard: ESLint, `tsc --noEmit`, 10 unit tests (node:test), production
  build; all pages rendered in Chromium (light/dark, 1440px and 390px) with no
  console errors and no horizontal overflow.
- ruff, ruff format, mypy --strict clean; pip-audit: no known vulnerabilities.

Known issues:
- (resolved) CI and Security workflows are green on GitHub.
- Not verifiable in the dev sandbox: API Dockerfile apt layer (Debian mirrors
  blocked), dashboard image (Docker Hub rate limit). CI builds both.
- Owner action: set `main` as the repository's default branch and add branch
  protection (require PR + passing CI/Security checks). Until the default
  branch is changed, new Dependabot PRs keep targeting the session branch.
- Seven Dependabot PRs (#1–#7) target the old session branch; left for the owner.
- Databases created before migrations existed (earlier builds of this
  session) are rejected with a clear message; recreate them.
- No real-model benchmark results yet (needs API keys; T-009b).

Technical debt:
- ESLint pinned to 9.x (eslint-plugin-react incompatible with ESLint 10).
- Vitest cannot be installed with npm 10.9 (resolver crash); web unit tests
  use node:test with type stripping.
- `service.py` executes work in-process (fine for one node).

Next priority:
- T-015b public beta readiness (CONTRIBUTING, templates, walkthrough, v0.2.0).

Project health:
- Green locally across backend and dashboard.
