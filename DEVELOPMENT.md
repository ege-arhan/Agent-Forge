# Development guide

## Setup

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), git. Optional:
Docker (sandbox tests, Compose), Node.js 20+ (dashboard).

```bash
git clone https://github.com/ege-arhan/Agent-Forge && cd Agent-Forge
uv sync --all-extras          # .venv with runtime, provider SDKs, dev tools
uv run agentforge --version
```

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

## Test layout

- `tests/unit` — components in isolation (providers use the real SDKs over a
  mocked HTTP transport).
- `tests/integration` — several components together: storage, benchmarks,
  experiments, the GitHub workflow against a local bare repository, Docker
  sandbox (marker `docker`).
- `tests/e2e` — through the HTTP API (FastAPI TestClient) and the CLI.

All tests are offline. The scripted provider stands in for models.

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
  attempt fails.

## Conventions

See `CLAUDE.md` → *Conventions*. In short: strict typing, no secrets in logs,
no fabricated metrics, tests for every change, docs only for real features.
