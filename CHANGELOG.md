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
- Example agents, starter benchmark suite and experiments.

### Fixed
- Sandboxed Python could execute stale bytecode after a same-second,
  same-size edit; sandboxes now set `PYTHONDONTWRITEBYTECODE=1`.
- Benchmark limits overrode stricter agent limits; they now act as caps.
- Timestamps lost their timezone on SQLite; all stored datetimes are now
  timezone-aware UTC.
