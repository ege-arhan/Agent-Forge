# AgentForge Development Status

Date: 2026-09-27

Version: **0.2.0** (release prepared; not tagged). Milestones 0–15 complete in
the release branch; the project is in **feature freeze** until the owner
starts milestone 16 or a future-work item (see ROADMAP.md).

## Branches and pull requests

Stable branch: `main` (at `7eb61d8`). All work reaches it through pull
requests merged by the owner; see CLAUDE.md "Git workflow".

Release branch: `claude/clever-bohr-woxzdb` (PR #11). Merge order:

1. #8 `claude/focused-newton-j0z9l1` — PR-based workflow docs.
2. #9 `feature/dogfooding-improvement-loop` — dogfooding program, improvement loop.
3. #10 `feature/real-model-validation` — real-model validation tooling.
4. #11 `claude/clever-bohr-woxzdb` — OpenCode Go fixes, REAL results, hard
   suite, improvement experiments, **PR #12 merged in** (human approval gate;
   conflicts resolved, its migration renumbered `0002` → `0003`), CI
   regression gate, v0.2.0 release preparation.

Each branch contains the previous one; #12 will show as merged once #11 is.
Dependabot PRs #1–#7 were closed as obsolete (they targeted the pre-`main`
default branch); Dependabot recreates needed updates once `main` is default.

## What 0.2.0 contains

- Runtime, providers (Anthropic, OpenAI-compatible incl. OpenCode Go, local,
  scripted), tools with guardrails, local and hardened Docker sandboxes,
  memory, evaluation, benchmarks, experiments, storage (SQLite/PostgreSQL,
  migrations 0001–0003), API, CLI, dashboard, GitHub issue → draft PR
  workflow, OpenTelemetry/Prometheus.
- Versioned agents and the improvement loop (analysis → proposal → new
  version → re-benchmark → comparison).
- Human approval gate for sensitive tools (T-004b).
- CI regression gate `agentforge bench gate` + `GET /benchmarks/gate` +
  GitHub Actions example (T-019).
- Dogfooding program: six agents, six suites (incl. `dogfood-hard`), OFFLINE
  reference solutions.

## Real-model validation (REAL, OpenCode Go) — final historical record

Documented in `docs/REAL_MODEL_BENCHMARK.md`; not rerun or altered.

- 5 models × 2 dogfood tasks: 10 executions, all passed (too easy to
  differentiate the models).
- `dogfood-hard`: `deepseek-v4.1-flash` passed the 2 tasks it ran (2 executions).
- Controlled improvement-loop demonstration: step limit 8 → failed at the
  limit; proposal `limits.max_steps` 8 → 25; v2 passed (2 executions);
  verdict `inconclusive`. A configuration-level change, not model learning.
- Totals: 14 task executions + 2 smoke calls, 107 model calls, 355 391
  tokens; cost NOT AVAILABLE. Small samples: no rankings, no significance.

## Verification (2026-09-27, release branch)

- Python: 355 tests passing (SQLite; includes 8 Docker-sandbox tests
  with a running daemon). Integration + e2e against PostgreSQL 16:
  121 passing.
- Dashboard: ESLint, `tsc --noEmit`, 17 unit tests, production build.
- ruff, ruff format, mypy --strict: clean. `ruff --select S`: clean.
- Security: gitleaks over all git history and the working tree, the stored
  results and the local experiment data — no findings; pip-audit — no known
  vulnerabilities; no OpenCode credential, Authorization header or bearer
  token in any file, result, log or git object. CodeQL runs in CI.
- Release dry run: `scripts/release_notes.py check v0.2.0` passes (all
  version strings 0.2.0), release notes extract from CHANGELOG, `uv build`
  produces `agentforge-0.2.0` sdist and wheel (migrations 0001–0003 included).

## Owner actions

See `docs/RELEASE_CHECKLIST.md` for the complete list. In short: merge
#8 → #9 → #10 → #11; set `main` as the default branch and protect it; push
the `v0.2.0` tag on `main`; rotate the OpenCode Go key; disable the old
"Agent Forge" routine and attach the repository to "AgentForge daily
development" (T-018).

## Known limitations

- Real-model evidence is small (one run per task); see REAL_MODEL_BENCHMARK.md.
- The approval gate runs in-process (single-node execution model).
- The regression gate compares against one baseline; trend baselines and
  richer policies are future work (T-019b).
- The rule-based proposer changes configuration and prompt guidance only.
- The `agentforge-sandbox` image cannot be built in this development
  environment (Debian mirrors blocked); CI builds it.
- Databases created before migrations existed are rejected with a clear
  message; recreate them.
