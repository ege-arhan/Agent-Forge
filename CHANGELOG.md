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
- Agent improvement loop (`agentforge.improvement`): failure analysis of
  benchmark runs (categories with evidence), deterministic rule-based or
  developer-written proposals limited to an allowlist of config paths,
  applying a proposal as a new agent version, re-benchmarking on the
  baseline's suite snapshot and comparing (Wilson intervals, per-task changes,
  verdict). CLI `agentforge improve analyze|propose|apply|evaluate|reject|run|history`,
  API `/improvements`, dashboard **Improvement** pages.
- Agent version history: every stored-agent change is an immutable snapshot
  (`GET /agents/{id}/versions`); benchmark runs record the agent version they
  ran.
- Result classes: benchmark runs are `offline` (scripted provider) or `real`,
  derived from the config; they are filtered, reported and shown separately
  and never compared with each other.
- Benchmark reports (`agentforge bench report`, `bench run --report`,
  `GET /benchmarks/runs/{id}/report`) with per-run checks, tool calls,
  retries, duration, tokens (`null` when unreported), estimated cost and
  `actual_cost_usd` (always `null`); `agentforge bench compare`.
- Dogfooding program (`dogfood/`): five agents (coding, debugging, data
  analysis, security analysis, GitHub issue solver), five suites with visible,
  hidden and process checks, offline reference agents, `scripts/dogfood.py`
  (offline and real modes) and the first OFFLINE results.
- Database migration `0002`: `agent_versions`, `improvement_cycles`,
  `benchmark_runs.agent_id/agent_version/result_class` (backfilled).
- `opencode-go` provider preset (OpenCode Go through the existing
  OpenAI-compatible provider; requires `model.base_url`, key from
  `OPENCODE_API_KEY`).
- Optional per-run token budget `limits.max_total_tokens` (off by default);
  runs that reach it stop with error type `token_budget` (failure category
  `token_budget`).
- `scripts/real_model_validation.py`: Limited Real-Model Validation harness
  (at most 15 sequential task executions, no retries, token budget, model
  listing preflight, REAL results only, secret scan) and
  `docs/REAL_MODEL_BENCHMARK.md`. Not run yet.
- `opencode-go` sends `x-opencode-session` on every model request (the run id:
  stable across a run's calls and retries, distinct per run; new
  `CompletionRequest.session_id`) and an `agentforge/<version>` user agent, as
  OpenCode Go requires. Without it OpenCode Go answered `400 MissingSessionID`.
- `opencode-go` routes models that OpenCode serves on `/responses` (e.g.
  `muse-spark-1.3-contributor`) through the Responses API; `/messages`-only
  models are refused before any request.
- OpenAI-compatible providers: `model.options.auth: proxy` for credentials
  injected by an egress proxy (e.g. Claude Cloud API Credentials): no key is
  read and no `Authorization` header is sent. The validation script exposes it
  as `--auth proxy`; `--auth env` (`OPENCODE_API_KEY`) stays the default.
- Validation script: single endpoint `https://opencode.ai/zen/go/v1` (no
  fallbacks), exact model ids, the unauthenticated `/models` listing is no
  longer treated as proof of authentication, a 401/403 model call stops the
  experiment, and a credential-pattern scan runs in both auth modes.
- `AGENTFORGE_BENCHMARKS_DIR` accepts several directories (default
  `examples/benchmarks:dogfood/benchmarks`).

### Changed
- Development workflow: `main` is the stable, always-releasable branch; all
  work (including autonomous sessions) happens on feature branches and
  reaches `main` only through pull requests merged by the owner.
- Updating a stored agent with an identical configuration no longer creates a
  new version.

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
- Concurrent updates of a stored agent could fail with a unique-constraint
  error on PostgreSQL; the agent row is now locked while the next version is
  allocated.
- Benchmark runs left running by a stopped API process stayed "running"
  forever; they (and interrupted improvement evaluations) are now marked
  failed on startup.
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
