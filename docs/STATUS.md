# AgentForge Development Status

Date: 2026-09-27

Current milestone: 15 — Public beta (Milestones 0–14 complete)

`main` exists and is the stable branch (created at `7eb61d8`); this session
developed on `claude/stoic-gates-es8u81`, branched fresh from `origin/main`.

Open pull requests awaiting the owner (stacked, each `mergeable_state: clean`
and CI-green at last check): `#8` (PR-based workflow docs, base `main`) →
`#9` (dogfooding program + agent improvement loop) → `#10` (real-model
validation prep, not yet run) → `#11` (OpenCode Go fixes + first real-model
results: 5 models × 2 easy tasks, all passed — too easy to differentiate
models; added a harder `dogfood-hard` suite and ran one real improvement
experiment, which found nothing to improve). This session did not duplicate
that work; see `ROADMAP.md` "Next up".

Completed this session:
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
  - Migration `0002` widens `runs.status` from `String(16)` to `String(24)`:
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

Completed (Milestones 0–14, prior sessions):
- M0 repository foundation (uv, ruff, mypy --strict, pytest, src layout, Apache-2.0)
- M1 core domain models and configuration
- M2 providers: Anthropic, OpenAI, OpenRouter, Gemini (OpenAI-compatible), local, scripted
- M3 agent runtime (retries, timeouts, cancellation, budgets, plan_execute, evaluation retries, events)
- M4 tool registry + executor + filesystem/terminal/git/http/github/memory tools
- M5 sandboxes (local; hardened Docker verified against a real daemon)
- M6 memory; M7 evaluation; M8 benchmarks; M9 experiments
- M10 GitHub: client, tools, issue → draft PR workflow via CLI, API and dashboard
- M11 web dashboard (Next.js 16, TypeScript, Tailwind 4), light/dark
- M12 OpenTelemetry + Prometheus; M13 sandbox egress control + API hardening
- M14 CI/CD, migrations, release automation
- HTTP API, CLI, Docker images, Compose, CI + security workflows, docs

Implemented:
- See CHANGELOG.md [Unreleased] and TASKS.md "Done".

Tests:
- Python: 204 tests (unit, integration, e2e) passing against SQLite.
- Integration + e2e (61 tests, including the new approval-gate tests) also
  pass against a real PostgreSQL 16 instance in this session's sandbox.
- Docker sandbox tests: not exercised this session (no daemon verified);
  unaffected by this session's changes.
- Dashboard: ESLint, `tsc --noEmit`, 10 unit tests (node:test), production
  build all clean; manually verified in headless Chromium (see above).
- ruff, ruff format, mypy --strict clean.

Known issues:
- No real-model benchmark results yet on `main` (needs API keys; T-009b) —
  PR `#11` has a first, inconclusive attempt awaiting merge.
- Seven Dependabot PRs (#1–#7) target the pre-`main` session branch
  `claude/focused-newton-j0z9l1`, not `main`; need retargeting or closing by
  the owner.
- Databases created before migrations existed (early builds) are rejected
  with a clear message; recreate them.

Technical debt:
- ESLint pinned to 9.x (eslint-plugin-react incompatible with ESLint 10).
- Vitest cannot be installed with npm 10.9 (resolver crash); web unit tests
  use node:test with type stripping.
- `service.py` executes work in-process (fine for one node); the approval
  gate follows the same model (in-process futures, not persisted — a server
  restart while a run is `awaiting_approval` fails it, like any other
  in-flight run).

Next priority:
- Owner: merge the open PR stack (`#8`→`#9`→`#10`→`#11`), set `main` as the
  default branch with branch protection, retarget or close the Dependabot
  PRs, decide on real-model budget for T-009b.
- T-015b public beta readiness (CONTRIBUTING, templates, walkthrough — done;
  remaining is the owner's v0.2.0 decision).

Project health:
- Green locally across backend (SQLite and PostgreSQL) and dashboard.
