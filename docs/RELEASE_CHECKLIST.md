# Release readiness checklist — v0.2.0

Date: 2026-09-27 · Release branch: `claude/clever-bohr-woxzdb` (PR #11) ·
Version: 0.2.0 (not tagged)

Each item is **PASS** (verified in this session) or **MANUAL ACTION
REQUIRED** (needs the owner or the GitHub/claude.ai UI). Nothing unknown is
marked PASS.

| Area | Status | Evidence / action |
|---|---|---|
| Architecture | PASS | Components and design decisions in `ARCHITECTURE.md`, including the regression gate and the approval gate; migrations form one chain 0001 → 0002 → 0003. |
| Tests | PASS | 355 Python tests (unit, integration, e2e, 8 Docker-sandbox tests with a daemon) on SQLite; 121 integration + e2e tests on PostgreSQL 16; 17 dashboard unit tests. |
| CI | PASS (branch) · MANUAL ACTION REQUIRED (`main`) | CI and Security workflows green on the release branch's pushed commits; `main` gets them once the stack is merged. |
| Security | PASS | gitleaks (all git history, working tree, results, local data): no findings; pip-audit: no known vulnerabilities; ruff `S`: clean; no OpenCode credential, Authorization header or bearer token in files, results, logs or git objects. CodeQL: green in CI. |
| Credentials | MANUAL ACTION REQUIRED | The OpenCode Go key is not in the repository, but it was pasted in chat and appeared on command lines during earlier sessions: **rotate it**. |
| Documentation | PASS | README (Agent CI/CD positioning, lifecycle, real-model limits), `docs/regression-gate.md`, `docs/REAL_MODEL_BENCHMARK.md`, CHANGELOG `[0.2.0]`, ROADMAP (future work separated), TASKS, STATUS. |
| Benchmarks | PASS | Six dogfood suites incl. `dogfood-hard` v1; reference solutions pass, idle agents fail, plausible wrong solutions fail the intended checks. |
| Real-model validation | PASS (as a limited, historical record) | 5 models, 10 + 2 + 2 task executions, documented with limitations; not rerun or altered. Broader studies are future work (T-009c). |
| Improvement loop | PASS | Offline demo and a controlled real-model demonstration; v1/v2 configs, benchmarks and the cycle exported to `dogfood/results/real/improvement-demo-*/history.json`. |
| Regression gate | PASS | `agentforge bench gate` (exit 0/1/2), API `GET /benchmarks/gate`, dashboard verdict, `.github/workflows/agentforge-regression.yml`; unit, CLI and API tests. |
| Approval gate | PASS | PR #12 merged into the release branch; its tests pass on SQLite and PostgreSQL; the improvement loop cannot change the approval policy (regression test). |
| GitHub integration | PASS | Issue → branch → commit → draft PR workflow; never merges; e2e tested against a mocked GitHub API and a local bare remote. |
| Release workflow | PASS (dry run) · MANUAL ACTION REQUIRED (tag) | `release_notes.py check v0.2.0` passes; notes extract from CHANGELOG; `uv build` produces `agentforge-0.2.0`. The workflow runs only on a `v*.*.*` tag, builds images, drafts the release and does not publish to PyPI. Owner pushes `v0.2.0` on `main` after the merges. |
| Version consistency | PASS | `pyproject.toml`, `agentforge.__version__`, `web/package.json`, `web/package-lock.json`, `uv.lock`: 0.2.0. |
| Dependency state | PASS | Lockfiles unchanged except the project version; Dependabot PRs #1–#7 closed as obsolete (wrong base branch). |
| Dependabot | MANUAL ACTION REQUIRED | Dependabot will open fresh PRs against `main` once `main` is the default branch; review them then. |
| Routine state | MANUAL ACTION REQUIRED | "AgentForge daily development": prompt updated (PR workflow, no merges/tags, no real-model calls without written approval, feature freeze); **attach the repository as its source**. "Agent Forge" (older, overlapping): **disable it** — agents cannot edit it. |
| Main branch protection | MANUAL ACTION REQUIRED | Verified unprotected (GitHub API: `protected: false`), and the default branch is still `claude/focused-newton-j0z9l1`. |

## Owner steps, in order

1. Review and merge **#8 → #9 → #10 → #11** (merge commits keep the history;
   #12 then shows as merged).
2. Settings → General: set **`main`** as the default branch.
3. Settings → Branches (or Rulesets) for `main`: require a pull request,
   require status checks — `Lint & format`, `Type check (mypy --strict)`,
   `Tests (Python 3.12)`, `Tests (Python 3.13)`, `Tests against PostgreSQL`,
   `Docker sandbox tests`, `Dashboard (lint, types, tests, build)`,
   `Docker images`, `CodeQL`, `Secret scanning (gitleaks)`,
   `Dependency vulnerabilities (pip-audit)`,
   `Static analysis (ruff security rules / bandit)` — block force pushes and
   deletions.
4. Tag the release on the merged `main` (fetch first; a merge on GitHub
   does not move a local `origin/main`):
   `git fetch origin main && git tag v0.2.0 FETCH_HEAD && git push origin v0.2.0`,
   check `git log -1 v0.2.0` shows the merge commit, then review and publish
   the draft release.
5. Rotate the OpenCode Go key.
6. Routines: disable "Agent Forge"; attach `ege-arhan/Agent-Forge` to
   "AgentForge daily development".
