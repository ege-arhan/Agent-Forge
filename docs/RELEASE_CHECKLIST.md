# Release readiness checklist — v0.2.0

Date: 2026-09-27 (release prepared), updated 2026-09-28 (release verified) ·
Released from: PR #11 (carrying #12), merged into `main` at `918f3bf` ·
Version: **0.2.0 — tagged and published**

Each item is **PASS** (verified in this session) or **MANUAL ACTION
REQUIRED** (needs the owner or the GitHub/claude.ai UI). Nothing unknown is
marked PASS. Rows below unchanged since 2026-09-27 record that session's
findings; the three rows about the release mechanics have been re-verified
against the live repository as of 2026-09-28.

| Area | Status | Evidence / action |
|---|---|---|
| Architecture | PASS | Components and design decisions in `ARCHITECTURE.md`, including the regression gate and the approval gate; migrations form one chain 0001 → 0002 → 0003. |
| Tests | PASS | 355 Python tests (unit, integration, e2e, 8 Docker-sandbox tests with a daemon) on SQLite; 121 integration + e2e tests on PostgreSQL 16; 17 dashboard unit tests. |
| CI | PASS | CI and Security workflows green on `main` at `918f3bf` (verified 2026-09-28 via the GitHub Actions API). |
| Security | PASS | gitleaks (all git history, working tree, results, local data): no findings; pip-audit: no known vulnerabilities; ruff `S`: clean; no OpenCode credential, Authorization header or bearer token in files, results, logs or git objects. CodeQL: green in CI. |
| Credentials | MANUAL ACTION REQUIRED | The OpenCode Go key is not in the repository, but it was pasted in chat and appeared on command lines during earlier sessions: **rotate it**. |
| Documentation | PASS | README (Agent CI/CD positioning, lifecycle, real-model limits), `docs/regression-gate.md`, `docs/REAL_MODEL_BENCHMARK.md`, CHANGELOG `[0.2.0]`, ROADMAP (future work separated), TASKS, STATUS. |
| Benchmarks | PASS | Six dogfood suites incl. `dogfood-hard` v1; reference solutions pass, idle agents fail, plausible wrong solutions fail the intended checks. |
| Real-model validation | PASS (as a limited, historical record) | 5 models, 10 + 2 + 2 task executions, documented with limitations; not rerun or altered. Broader studies are future work (T-009c). |
| Improvement loop | PASS | Offline demo and a controlled real-model demonstration; v1/v2 configs, benchmarks and the cycle exported to `dogfood/results/real/improvement-demo-*/history.json`. |
| Regression gate | PASS | `agentforge bench gate` (exit 0/1/2), API `GET /benchmarks/gate`, dashboard verdict, `.github/workflows/agentforge-regression.yml`; unit, CLI and API tests. |
| Approval gate | PASS | PR #12 merged into the release branch; its tests pass on SQLite and PostgreSQL; the improvement loop cannot change the approval policy (regression test). |
| GitHub integration | PASS | Issue → branch → commit → draft PR workflow; never merges; e2e tested against a mocked GitHub API and a local bare remote. |
| Release workflow | PASS | `release_notes.py check v0.2.0` passed pre-merge; `v0.2.0` is tagged on `main` (`918f3bf`) and published as a GitHub release (verified 2026-09-28, not a draft). |
| Version consistency | PASS | `pyproject.toml`, `agentforge.__version__`, `web/package.json`, `web/package-lock.json`, `uv.lock`: 0.2.0. |
| Dependency state | PASS | Lockfiles unchanged except the project version; Dependabot PRs #1–#7 closed as obsolete (wrong base branch); no open Dependabot PRs against `main` as of 2026-09-28. |
| Dependabot | PASS | `main` is now the default branch, so Dependabot targets it; none open yet as of 2026-09-28 — review them as they appear. |
| Routine state | MANUAL ACTION REQUIRED — cannot be checked or changed from a coding session | "AgentForge daily development": prompt updated (PR workflow, no merges/tags, no real-model calls without written approval); **attach the repository as its source**. "Agent Forge" (older, overlapping): **disable it** — agents cannot edit it. |
| Main branch protection | UNKNOWN as of 2026-09-28 | `main` is confirmed the default branch (GitHub API), but this session's token gets `403 Resource not accessible` reading `/branches/main/protection`, so protection status could not be re-verified; assume unprotected until the owner confirms otherwise. |
| Credentials (OpenCode Go key) | MANUAL ACTION REQUIRED — cannot be verified from a coding session | Recorded 2026-09-27 as pasted in chat/command lines during earlier sessions; rotation cannot be confirmed by inspecting the repository. |

## Owner steps remaining

1. Confirm `main` branch protection (require PRs and the CI/Security status
   checks listed below; block force pushes and deletions) — this session's
   GitHub token cannot read or set branch protection.
2. Rotate the OpenCode Go key, if not already done.
3. Routines: disable "Agent Forge"; attach `ege-arhan/Agent-Forge` to
   "AgentForge daily development" (T-018).

Status checks to require once protection is set: `Lint & format`,
`Type check (mypy --strict)`, `Tests (Python 3.12)`, `Tests (Python 3.13)`,
`Tests against PostgreSQL`, `Docker sandbox tests`,
`Dashboard (lint, types, tests, build)`, `Docker images`, `CodeQL`,
`Secret scanning (gitleaks)`, `Dependency vulnerabilities (pip-audit)`,
`Static analysis (ruff security rules / bandit)`.
