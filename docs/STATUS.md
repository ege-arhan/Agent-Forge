# AgentForge Development Status

Date: 2026-11-21

Version: **0.2.0** (release prepared; not tagged). Milestones 0–15 complete in
the release branch; the project is in **feature freeze** until the owner
starts milestone 16 or a future-work item (see ROADMAP.md).

## Update 2026-11-21

- **Dashboard dependency advisories, fixed on branch
  `claude/stoic-gates-op93zt` (PR against `main`, independent of every other
  open PR).** `npm audit` on `main`'s `web/package-lock.json` reported 11
  advisories (1 critical, 3 high, 7 moderate): Next.js 16.3.6 (among them
  remote code execution and request forgery in the image optimizer, and
  cache poisoning in self-hosted deployments), `sharp`, `zod`,
  `source-map-js`, and `minimatch` under the lint tooling. No CI job audited
  npm packages — the Security workflow covered Python only — and Dependabot
  did not watch `web/`, so nothing reported them. Whether each advisory can
  be reached in this dashboard was not assessed.
- The fix: Next.js and `eslint-config-next` 16.3.6 → 16.4.6, `npm audit fix`
  for the rest (lockfile only); a new Security job
  *Dashboard dependency vulnerabilities (npm audit)*; `web/` added to
  Dependabot; `agentRules: false` in `web/next.config.ts`, because Next.js
  16.4 writes `AGENTS.md`/`CLAUDE.md` into the project on each build.
- Verified locally on that branch: `npm audit` reports 0 advisories (the new
  job's two commands exit 1 on the old lockfile and 0 on the new one); clean
  `npm ci`, lint, typecheck, 17 unit tests and the production build pass;
  the built dashboard was opened in a browser against a running API (all
  nine top-level pages and an agent page render, no console errors).
  Python code untouched: ruff and the 347 non-Docker tests pass (mypy, the
  Docker-sandbox and PostgreSQL tests were not run here). The dashboard
  image is built by CI, not here.
- `main` is still at `9a0f8fb`; CI on it and the scheduled Security run of
  2026-11-16 were green. Nothing has been merged since 2026-11-01. Agent PRs
  awaiting review: #40 → #41 → #42 → #44 → #45 → #46 (a stack; each contains
  the ones before it, and #40 contains #13, #32–#34 and #37–#39), plus a
  YAML-import PR from `feature/agent-yaml-import` stacked on #46. The stack's
  own `docs/STATUS.md` describes them. Those branches carry the same
  vulnerable lockfile until this fix is merged into them.
- Dependabot PRs #15–#19, #27–#31 and #36 are open (the owner's to merge;
  their CI was not checked this session).

## Update 2026-10-31

- v0.2.0 is merged and tagged on `main` (`244f660`, tag `v0.2.0`); the
  "release prepared; not tagged" and merge-order text below is historical.
- CI on `main` was green except the scheduled **Security** run of 2026-10-26:
  `pip-audit` flagged `certifi` 2026.7.22 (PYSEC-2026-4320) and
  `opentelemetry-api` 1.45.0 (CVE-2026-114603). Fixed on branch
  `claude/stoic-gates-yxaatl` by a lockfile update only; local `pip-audit`
  now reports no known vulnerabilities, ruff/mypy clean, 347 non-docker tests
  pass (docker tests and web not run this session; web untouched).
- Awaiting owner review: agent PRs #13 (native Gemini adapter), #32 (gate
  token/latency budgets), #33, #34 (review fixes); Dependabot PRs #14–#19,
  #27–#31 (owner's to merge; not checked for failures this session).

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
