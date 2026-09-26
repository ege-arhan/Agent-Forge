# Development guide

## Setup

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), git. Optional:
Docker (sandbox tests, Compose), Node.js 20+ (dashboard).

```bash
git clone https://github.com/ege-arhan/Agent-Forge && cd Agent-Forge
uv sync --all-extras          # .venv with runtime, provider SDKs, dev tools
uv run agentforge --version
```

## Branching and pull requests

`main` is the stable, always-releasable branch. Nobody — human or AI session
— commits to it directly.

1. **Before starting**, look at `main` (recent commits, CI status) and the
   open pull requests, so you build on the latest state and do not duplicate
   work in flight.
2. **Branch** from the latest `main`: `git checkout -B feature/<topic>
   origin/main` (automated sessions use their `claude/<name>` branch). Only
   branch from another open PR when your change depends on it, and say so in
   the PR description.
3. **Verify** locally before opening a PR: ruff, ruff format, mypy, the full
   pytest suite (with Docker for sandbox tests), and the dashboard checks if
   `web/` changed. Update the changelog and project-status files.
4. **Open a PR against `main`** using the template, listing the tests you ran.
   CI must be green. Pull requests are never merged automatically; the
   repository owner reviews and merges them.
5. **Release** only from `main` (see *Releasing*).

Recommended repository settings (owner): make `main` the default branch and
protect it — require a pull request, require the CI and Security checks to
pass, and disallow force pushes and deletions.

## Everyday commands

| Task | Command |
|---|---|
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Type check (strict) | `uv run mypy` |
| All tests | `uv run pytest` |
| Fast unit tests | `uv run pytest tests/unit` |
| Without Docker | `uv run pytest -m "not docker"` |
| Docker sandbox tests | `docker pull python:3.12-slim && uv run pytest -m docker` |
| Against PostgreSQL | `AGENTFORGE_TEST_DATABASE_URL=postgresql+asyncpg://u:p@localhost/db uv run pytest tests/integration tests/e2e` |
| Coverage | `uv run pytest --cov` |
| API server | `uv run agentforge serve` → http://127.0.0.1:8000/docs |
| Offline demo | `uv run agentforge bench run examples/benchmarks/starter.yaml -a examples/agents/scripted-demo.yaml` |
| Dogfooding (offline) | `uv run python scripts/dogfood.py offline` (writes `dogfood/results/offline/`) |
| Dogfooding (real model) | `uv run python scripts/dogfood.py real --provider anthropic --model <id>` (needs the key; writes `dogfood/results/real/`) |
| Improvement loop | `uv run agentforge improve run BENCH_ID` — see [docs/improvement.md](docs/improvement.md) |

## Test layout

- `tests/unit` — components in isolation (providers use the real SDKs over a
  mocked HTTP transport).
- `tests/integration` — several components together: storage, benchmarks,
  experiments, the GitHub workflow against a local bare repository, Docker
  sandbox (marker `docker`).
- `tests/e2e` — through the HTTP API (FastAPI TestClient) and the CLI.

All tests are offline. The scripted provider stands in for models.

## Database migrations

The schema is managed with Alembic (`src/agentforge/storage/migrations`).
The API server and CLI upgrade the database automatically; `agentforge db
upgrade` and `agentforge db current` do it explicitly.

After changing ORM models in `storage/db.py`:

```bash
AGENTFORGE_DATABASE_URL=sqlite+aiosqlite:////tmp/af-migrate.db \
  uv run alembic -c src/agentforge/storage/migrations/alembic.ini upgrade head
AGENTFORGE_DATABASE_URL=sqlite+aiosqlite:////tmp/af-migrate.db \
  uv run alembic -c src/agentforge/storage/migrations/alembic.ini \
  revision --autogenerate -m "describe the change" --rev-id 000N
```

Review the generated file (JSONB variants need `sa.Text()`), then run the
tests: `tests/integration/test_migrations.py` fails if models and migrations
diverge (on SQLite locally and on PostgreSQL in CI).

## Releasing

1. Bump the version in `pyproject.toml`, `src/agentforge/__init__.py` and
   `web/package.json` (a unit test enforces that they match).
2. Move the `## [Unreleased]` entries in `CHANGELOG.md` under
   `## [X.Y.Z] - YYYY-MM-DD`.
3. After the release PR is merged into `main`, the owner tags `main`:
   `git tag vX.Y.Z origin/main && git push origin vX.Y.Z`.

`.github/workflows/release.yml` then verifies the version strings, builds the
wheel and sdist, publishes `agentforge-api`, `agentforge-web` and
`agentforge-sandbox` images to GHCR (`ghcr.io/<owner>/...:X.Y.Z` and `:X.Y`),
and creates a **draft** GitHub release with the changelog section and
distribution files attached. A maintainer reviews and publishes the draft.
PyPI publishing is not configured (it needs a trusted publisher set up by the
repository owner).

## Adding things

- **Tool:** subclass `Tool[YourInput]` (see `tools/builtin/filesystem.py`),
  set `name`, `description`, `input_model`, `permissions`, `timeout_seconds`,
  register it in a toolset in `tools/builtin/__init__.py` (or publish it via the
  `agentforge.tools` entry-point group) and add tests through `ToolExecutor`.
- **Provider:** implement `LLMProvider.complete`, translate errors to
  `LLMError(retryable=...)`, register a factory in `llm/registry.py` (or the
  `agentforge.providers` entry-point group), test over a mock transport.
- **Evaluator:** subclass `Evaluator` with a `Params` model and `check()`,
  decorate with `@register_evaluator` (or use `type: python` with
  `class: module:Class`, or the `agentforge.evaluators` entry-point group).
- **Benchmark task:** add it to a suite YAML with setup, allowed tools and
  deterministic evaluators; make sure a correct solution passes and an empty
  attempt fails. For `dogfood/benchmarks/`, add the reference solution to the
  matching `dogfood/agents/offline/*.yaml`; the integration tests check both
  directions. Changing an existing task requires bumping the suite `version`.

## Scheduled autonomous sessions (routines)

Development is continued by scheduled Claude Code routines. A routine's
session can only continue from the latest `main` if the routine itself gives
it the repository. Inspected on 2026-09-26 (from a session, via the routines
API):

| Routine | Schedule | Repository / connectors | Prompt | Assessment |
|---|---|---|---|---|
| **AgentForge daily development** (`trig_01PkiuJ7…`) | daily 08:46 Europe/Istanbul, fresh session each run, environment "Default" | **no repository source attached**, no connectors | current workflow (inspect `main` and PRs, feature branch, PR, never merge) | **Not reliable.** The fired session starts without a checkout. Its fallbacks (attach the repo from inside the session, or an anonymous `git clone` of the public repo) give at best read access: pushing a branch and opening a PR need the repository attached to the session with GitHub credentials. |
| **Agent Forge** (`trig_014Bbty…`) | daily 06:47 UTC, fresh session each run | connectors: Claude-Docs, visualize (no GitHub); repository attachment not visible through the API | **outdated**: predates the `main`/PR workflow | Runs a second, overlapping daily session with conflicting instructions. |

Required owner changes (in claude.ai → Claude Code → Routines):

1. Edit **AgentForge daily development** and add the repository
   `ege-arhan/Agent-Forge` as its source, keeping the "Default" environment.
   GitHub must be connected to the account (claude.ai/connect-github) and the
   Claude GitHub App installed on the repository. Without this step the
   routine cannot push or open pull requests.
2. Disable (or delete) the older **Agent Forge** routine, or replace its
   prompt with the daily-development prompt and attach the repository to it
   too. Only one routine should develop the repository.
3. Optional, for real-model dogfooding (T-009b): add a provider key (e.g.
   `ANTHROPIC_API_KEY`) as an environment variable in the "Default"
   environment's settings, and decide on an API budget. Without it,
   `scripts/dogfood.py real` refuses to run and records nothing.
4. Make `main` the default branch and protect it (see *Branching and pull
   requests*).

To verify: after the next scheduled run, a new pull request from a `claude/*`
branch should target `main`. If the run's summary says it could not clone or
push, step 1 is still missing.

## Conventions

See `CLAUDE.md` → *Conventions*. In short: strict typing, no secrets in logs,
no fabricated metrics, tests for every change, docs only for real features.
