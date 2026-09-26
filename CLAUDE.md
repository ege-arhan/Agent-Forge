# CLAUDE.md — instructions for AI engineering sessions

AgentForge is developed largely by autonomous Claude Code sessions. The
repository is the only persistent memory: **never rely on anything from a
previous session that is not written down here or in the files below.**

## Session protocol

At the start of every session:

1. Read this file, `ROADMAP.md`, `TASKS.md`, `docs/STATUS.md`, `ARCHITECTURE.md`.
2. `git status`, `git log --oneline -20`, `git branch -a` — find the most recent
   work (see *Branches* below).
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
- Review `git diff`, commit with a descriptive message, push.

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

## Branches

- Work happens on the branch named by the session instructions
  (`claude/<name>`). Never push to other branches without permission.
- If `main` does not contain the latest work, check `git branch -a` and the
  most recently updated `claude/*` branch; `docs/STATUS.md` records which
  branch holds the latest state.

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
