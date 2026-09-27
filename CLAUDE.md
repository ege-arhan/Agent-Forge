# CLAUDE.md — instructions for AI engineering sessions

AgentForge is developed largely by autonomous Claude Code sessions. The
repository is the only persistent memory: **never rely on anything from a
previous session that is not written down here or in the files below.**

## Session protocol

At the start of every session:

1. Read this file, `ROADMAP.md`, `TASKS.md`, `docs/STATUS.md`, `ARCHITECTURE.md`.
2. Inspect `main`, open pull requests and CI (see *Git workflow* below)
   before starting new work.
3. Set up the environment and run the checks (commands below). If anything is
   red, fixing it is the first task.
4. Pick the highest-value incomplete task from `TASKS.md` (P0 before P1 before
   P2, respecting dependencies and the milestone order in `ROADMAP.md`).
5. Plan → implement → test → debug → self-review → document → commit → push.

Before ending a session:

- Run lint, type check and the full test suite; everything must pass.
- Update `TASKS.md` (status, remaining work), `ROADMAP.md`, `CHANGELOG.md`
  (under *Unreleased*) and `docs/STATUS.md` (dated, factual — never claim
  unverified progress).
- Review `git diff`, commit with a descriptive message, push your feature
  branch and open (or update) a pull request against `main`. Never merge.

## Commands

```bash
uv sync --all-extras                 # create .venv with all extras + dev tools
uv run ruff check . && uv run ruff format --check .
uv run mypy                          # strict
uv run pytest                        # all tests (docker tests skip without a daemon)
uv run pytest -m "not docker"        # what the main CI job runs
uv run pytest -m docker              # needs a Docker daemon + python:3.12-slim
AGENTFORGE_TEST_DATABASE_URL=postgresql+asyncpg://u:p@host/db uv run pytest tests/integration tests/e2e
uv run agentforge --help
uv run agentforge bench run examples/benchmarks/starter.yaml -a examples/agents/scripted-demo.yaml
uv run agentforge serve              # API on :8000, docs at /docs
cd web && npm ci && npm run dev      # dashboard on :3000 (expects the API on :8000)
```

In cloud sessions without a Docker daemon, `dockerd &` usually works; Debian
apt mirrors and ghcr.io may be blocked by the environment's network policy.

## Git workflow (mandatory)

`main` is the stable branch and must **always be releasable**. All work
reaches it only through reviewed pull requests merged by the owner.

**Never** commit or push to `main`, force-push it, merge any pull request
(including Dependabot's), or push tags. Never push to branches other than
your own feature branch without the owner's permission.

### 1. Start of every session: inspect `main` and open PRs first

```bash
git fetch origin --prune
git log --oneline -15 origin/main               # what is released
# Open PRs (GitHub tools, or without them:)
curl -s "https://api.github.com/repos/ege-arhan/Agent-Forge/pulls?state=open&per_page=50" \
  | python3 -c "import json,sys; [print(p['number'], p['head']['ref'], '->', p['base']['ref'], '|', p['title']) for p in json.load(sys.stdin)]"
# CI on main and on open PR branches:
curl -s "https://api.github.com/repos/ege-arhan/Agent-Forge/actions/runs?per_page=10" \
  | python3 -c "import json,sys; [print(r['head_branch'], r['name'], r['status'], r['conclusion']) for r in json.load(sys.stdin)['workflow_runs']]"
```

Then, before starting anything new:

- If CI on `main` is red, fixing it (via a PR) is the top priority.
- For each open agent PR: check its CI and review comments. Address failures
  and feedback first — push to that PR's branch if your session is allowed
  to, otherwise open a follow-up PR from your branch that references it.
- Do not duplicate work that an open PR already covers; record in
  `docs/STATUS.md` which PRs are awaiting review.
- Dependabot PRs are the owner's to merge; note failing ones in STATUS.

### 2. Develop on a feature branch

Use your session's designated branch (`claude/<name>`) or `feature/<topic>`,
always created from the latest `origin/main`:

```bash
git checkout -B <feature-branch> origin/main
```

If the work genuinely depends on an unmerged open PR, branch from that PR's
head instead and state the dependency ("depends on #N; merge #N first") in
the PR description. Keep one coherent change per PR where practical.

### 3. Verify before opening a PR

Run everything relevant and make sure it passes:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest                                   # start dockerd for docker tests
cd web && npm ci && npm run lint && npm run typecheck && npm test && npm run build   # if web/ changed
```

Update `TASKS.md`, `ROADMAP.md`, `CHANGELOG.md` (*Unreleased*) and
`docs/STATUS.md` in the same branch.

### 4. Open a pull request against `main` — never merge it

Push the branch (`git push -u origin <feature-branch>`) and open a PR with
base `main`, following `.github/pull_request_template.md` (summary, changes,
tests run and their results, checklist). Then watch CI and push fixes to the
same branch until it is green. The owner reviews and merges.

## Conventions

- Python 3.12+, `src/` layout, package `agentforge`. Pydantic v2 models,
  SQLAlchemy 2 async, FastAPI. `mypy --strict` and ruff must stay clean.
- Provider-neutral core: nothing outside `agentforge/llm/<provider>.py` may
  depend on a vendor SDK. Vendor SDKs are optional extras, imported lazily.
- Tools: subclass `agentforge.tools.base.Tool`, declare `input_model`,
  `permissions`, `timeout_seconds`; register in a toolset. The executor
  handles validation, permissions, timeouts, truncation and redaction.
- Never log or persist secrets; route text through `Redactor`.
- Never fabricate metrics. Cost is `None` when pricing is unknown.
- Schema changes need an Alembic migration (see DEVELOPMENT.md); the
  migration test fails if models and migrations diverge.
- Every behaviour change needs tests. Bugs: reproduce → regression test → fix.
  Never delete or weaken tests to make CI pass.
- Docs describe only what exists. Mark planned features as planned.
- The scripted provider is for tests/demos only; never present its results
  as model performance.
- GitHub integration never merges PRs; PRs are drafts requiring human review.

## Where things are

See `ARCHITECTURE.md` for the component map. Quick index:
`core/` models+config · `llm/` providers · `runtime/` agent loop · `tools/`
registry+executor+builtins · `sandbox/` local+docker · `memory/` ·
`evaluation/` · `benchmarks/` · `experiments/` · `storage/` · `api/` ·
`service.py` background execution · `cli.py` · `integrations/github/` ·
`web/` dashboard (Next.js).
