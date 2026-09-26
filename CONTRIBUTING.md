# Contributing to AgentForge

Thanks for your interest! AgentForge aims to be a trustworthy tool for
engineering and evaluating agents, so correctness, security and honest
measurement matter more than feature count.

## Getting started

```bash
git clone https://github.com/ege-arhan/Agent-Forge && cd Agent-Forge
uv sync --all-extras
uv run pytest            # everything runs offline
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for commands, test layout, migrations,
releases and how to add tools, providers, evaluators and benchmark tasks.
[ARCHITECTURE.md](ARCHITECTURE.md) explains the components and design
decisions.

## Pull requests

- Branch from the latest `main` and open your pull request against `main`
  (see *Branching and pull requests* in DEVELOPMENT.md). `main` must always
  stay releasable; maintainers merge after review.
- Keep changes focused; open an issue first for larger features.
- Every behaviour change needs tests; bug fixes need a regression test that
  fails without the fix.
- These must pass: `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy`, `uv run pytest`, and for dashboard changes
  `npm run lint && npm run typecheck && npm test && npm run build` in `web/`.
- Schema changes need an Alembic migration (see DEVELOPMENT.md).
- Update docs and `CHANGELOG.md` (*Unreleased*) for user-visible changes.
  Documentation must describe what actually exists.

## Ground rules

- Never log, persist or expose secrets; use the `Redactor`.
- Never fabricate metrics — unknown values (e.g. cost without pricing) stay
  unknown.
- Agent output is untrusted: new tools must declare permissions, validate
  input, stay inside the workspace and go through the `ToolExecutor`.
- The GitHub integration must never merge pull requests.
- Benchmark results describe specific configurations; avoid claims of
  general model rankings.

## Reporting security issues

Please do not open public issues for vulnerabilities; follow
[SECURITY.md](SECURITY.md).

## Code of conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
