# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Core domain models: agent configuration, runs, steps, tool-call and LLM-call
  records, evaluation results, metrics.
- Provider-neutral LLM layer with adapters for Anthropic (official SDK) and
  OpenAI-compatible APIs (OpenAI, OpenRouter, Gemini, local servers), a
  deterministic scripted provider, a pricing table that reports cost only when
  pricing is known, and a provider plugin registry.
- Agent runtime with ReAct and plan-and-execute strategies, jittered LLM
  retries, run timeout, cancellation, step/tool-call budgets, consecutive
  tool-error cap, evaluation-driven retries and lifecycle events.
- Tool system: registry with toolsets and entry-point plugins; executor with
  input validation, permission policy, timeouts, truncation and secret
  redaction; filesystem, terminal, git, HTTP (SSRF-protected), GitHub and
  memory tools.
- Sandboxes: workspace path confinement, local process sandbox, hardened
  per-run Docker sandbox.
- Memory: context compaction, lexical search, in-memory and SQL stores.
- Evaluation engine with nine built-in evaluators, custom Python evaluators and
  objective run metrics.
- Benchmark engine (YAML suites, repeats, statistics with Wilson intervals) and
  experiment tracking with variant comparison.
- Async SQLAlchemy storage (SQLite default, PostgreSQL supported).
- FastAPI HTTP API with background execution, SSE events and optional API key.
- `agentforge` CLI.
- GitHub integration: REST client, tools, issue → branch → commit → draft PR
  workflow (never merges).
- Web dashboard (Next.js, TypeScript, Tailwind): overview, agents, runs with
  execution-trace viewer, benchmarks, experiments with confidence intervals,
  repositories, GitHub tasks, settings; light and dark themes.
- GitHub API endpoints: repository inspection, issues, background issue tasks.
- `/stats` reports known cost, runs with unknown pricing and token totals.
- Docker images (API, sandbox, dashboard), Compose setup, CI and security
  workflows.
- OpenTelemetry trace export (`agentforge[otel]`, `AGENTFORGE_OTEL_ENABLED`)
  with GenAI semantic-convention attributes, and a Prometheus `/metrics`
  endpoint.
- Alembic database migrations applied automatically by the API and CLI;
  `agentforge db upgrade` / `agentforge db current`.
- Tag-triggered release workflow (draft GitHub release, GHCR images).
- CONTRIBUTING.md, code of conduct, issue and pull request templates.
- Example agents, starter benchmark suite and experiments.

### Security
- Server-side policy for API-submitted configs and evaluators: prevents
  sending server credentials to caller-chosen endpoints (`base_url`,
  `api_key_env`, GitHub `api_url`/`token_env`), re-enabling private-network
  HTTP, arbitrary-import evaluators and unapproved sandbox settings.
- Sandbox egress control: operator-defined internal networks with an
  allowlisting egress proxy (`agentforge.sandbox.egress_proxy`), sandbox proxy
  settings and a selectable Docker runtime (e.g. gVisor `runsc`).
- Request size limit, per-client rate limiting, background-task cap,
  security headers and an audit log for state-changing API calls.

### Fixed
- Sandboxed Python could execute stale bytecode after a same-second,
  same-size edit; sandboxes now set `PYTHONDONTWRITEBYTECODE=1`.
- Benchmark limits overrode stricter agent limits; they now act as caps.
- Timestamps lost their timezone on SQLite; all stored datetimes are now
  timezone-aware UTC.
- Benchmark tasks whose setup failed referenced a run that was never stored;
  the failed run is now recorded.
- Cancelling a run not held by the current process left `finished_at` empty.
- The run event stream could stay open after a run finished when a slow
  client's queue was full.
- Real-model example agents used a sandbox image without git/pytest; they now
  use the provided `agentforge-sandbox` image.
