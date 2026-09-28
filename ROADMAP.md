# Roadmap

Milestones are built in order; each leaves the application runnable. Status
reflects what is merged in the repository (see `docs/STATUS.md` for the
latest session report and `TASKS.md` for task-level detail).

| # | Milestone | Status |
|---|---|---|
| 0 | Repository foundation (packaging, tooling, layout) | ✅ Done |
| 1 | Architecture and core domain models | ✅ Done |
| 2 | LLM provider abstraction (Anthropic, OpenAI, OpenRouter, Gemini (native), local, scripted) | ✅ Done |
| 3 | Agent runtime (loop, retries, limits, cancellation, planning, events) | ✅ Done |
| 4 | Tool registry (filesystem, terminal, git, HTTP, GitHub, memory; plugins) | ✅ Done |
| 5 | Sandbox (workspace confinement, local, hardened Docker) | ✅ Done — stronger isolation options planned |
| 6 | Memory (context compaction, persistent agent memory, memory tools) | ✅ Done — vector store planned (P2) |
| 7 | Evaluation engine (built-in + custom + LLM judge, metrics) | ✅ Done |
| 8 | Benchmark engine (suites, repeats, statistics, storage) | ✅ Done |
| 9 | Experiment tracking (variants, comparison, storage) | ✅ Done |
| 10 | GitHub integration (client, tools, issue → draft PR workflow, API, dashboard) | ✅ Done |
| 11 | Web dashboard | ✅ Done — enhancements tracked in T-011b |
| 12 | Observability (structured logs, events/SSE, OpenTelemetry traces, Prometheus metrics) | ✅ Done |
| 13 | Security hardening (API policy, limits, audit, sandbox egress control, gVisor option) | ✅ Done — see SECURITY.md limitations |
| 14 | CI/CD and developer experience (CI, security scans, migrations, release workflow) | ✅ Done |
| 15 | Public beta / v0.2.0: stable `main` + PR workflow, dogfooding program, agent improvement loop, human approval gate, CI regression gate, limited real-model validation | ✅ Done and released — PRs #8–#12 merged, `main` is the default branch, `v0.2.0` tagged and published (verified 2026-09-28) |
| 16 | Portfolio-quality release (screenshots, demo, polished docs) | ⏳ Planned — screenshots already in `docs/screenshots/` and embedded in the README; a recorded demo and a broader documentation pass remain |

v0.2.0 is released; the project is no longer in feature freeze. Ongoing work
follows this roadmap's milestone order and the P1/P2 items in `TASKS.md`.

## Next up (owner)

- Rotate the OpenCode Go key; disable the old "Agent Forge" routine and attach
  the repository to "AgentForge daily development" (T-018) — session-side
  code cannot verify or change either from here.

## Future work (not started; not part of v0.2.0)

- Stronger benchmark suites: larger, SWE-style tasks with harder hidden checks
  (T-008b).
- Richer failure analysis: trace-level diagnosis, e.g. planning vs reasoning
  failures (T-020).
- More sophisticated improvement proposals: an optional LLM-assisted proposer
  within the same allowlist (T-017b).
- Broader model evaluations: more tasks, repeats and models, and a real
  improvement cycle on an unconstrained failure; needs a budget (T-009c).
- More regression policies: per-check/per-category thresholds, token and
  latency budgets, trend baselines, required repeats (T-019b).
- Also planned: vector memory (T-006b), streaming output (T-003b), distributed
  execution (T-015), dashboard enhancements (T-011b).
