# AgentForge Development Status

Date: 2026-11-12

Version: **0.2.0** (released; tag `v0.2.0` on `main`). Milestones 0–15 are
complete; the project is in **feature freeze** (fixes, tests, security and
documentation only). Milestone 16 (documentation/demo work) is in progress.
Sections below the dated updates are the historical v0.2.0 release record.

## Update 2026-11-12

- `main` (`9a0f8fb`) is green: CI on the last push and the scheduled Security
  run of 2026-11-09 succeeded.
- Agent PRs awaiting owner review: #37 (offline tour; CI green, no review
  comments — the Codex review bot could not run, usage limit), #13, #32, #33,
  #34 (unchanged since October; not re-checked beyond their unchanged state).
  Dependabot PRs #15–#19, #27–#31, #36 are the owner's (not checked).
- Milestone 16 continued on `claude/stoic-gates-za4zoq`, **stacked on #37**
  (merge #37 first): reproducible screenshots (`scripts/screenshots.py`,
  `scripts/screenshots.cjs`), all of `docs/screenshots/` regenerated from the
  current dashboard with OFFLINE demo data plus a new approval-gate picture,
  docs index `docs/README.md`, README pass ("What is tested", link bar,
  shorter positioning text, current roadmap note), a Markdown link/anchor
  checker test. No package, API, schema or dashboard code changed.
- Verified this session: ruff, ruff format, mypy --strict clean;
  `pytest -m "not docker"` 382 passed; the screenshot pipeline ran end to
  end here (API + `next dev` + headless Chromium, 8 pictures). Not run:
  Docker-sandbox tests, PostgreSQL tests, web lint/typecheck/tests/build (no
  web code changed; `npm ci` and the dev server worked).
- Noticed, not fixed (T-021 remaining): the *Improvement history* table on
  `/improvement` clips its last column at 1440 px; the sidebar is one
  viewport tall on long pages. `next dev` writes `web/AGENTS.md` and
  `web/CLAUDE.md`; they are now git-ignored rather than committed — the
  owner may prefer to commit them.
- Remaining for milestone 16: a recording of the tour, the dashboard polish
  above.

## Update 2026-11-11

- `main` (`9a0f8fb`, includes #35) is green: CI and the scheduled Security
  runs of 2026-11-02 and 2026-11-09 succeeded.
- Agent PRs awaiting owner review, all with green CI and no unaddressed
  review comments: #13 (native Gemini adapter), #32 (gate token/latency
  budgets), #33 (review fixes for #13/#32), #34 (review fixes for #33).
  Dependabot PRs #15–#19, #27–#31, #36 are the owner's (not checked this
  session).
- Started milestone 16 (documentation/demo work, allowed in the freeze):
  offline five-minute tour — `scripts/tour.py`, `docs/tour.md` (a real
  transcript of the script; ids differ per run), README link,
  `tests/e2e/test_tour.py` (T-021, PR from `claude/stoic-gates-773dp5`).
  OFFLINE (scripted) results only; no model calls.
- Verified this session: ruff, ruff format, mypy --strict clean;
  `pytest -m "not docker"` 351 passed. Docker tests, PostgreSQL tests and the
  web checks were not run (no Python package or web code changed).
- Remaining for milestone 16: refreshed screenshots, a recording of the tour,
  a README pass and a docs index (see T-021).

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
