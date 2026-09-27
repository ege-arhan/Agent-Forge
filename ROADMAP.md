# Roadmap

Milestones are built in order; each leaves the application runnable. Status
reflects what is merged in the repository (see `docs/STATUS.md` for the
latest session report and `TASKS.md` for task-level detail).

| # | Milestone | Status |
|---|---|---|
| 0 | Repository foundation (packaging, tooling, layout) | ✅ Done |
| 1 | Architecture and core domain models | ✅ Done |
| 2 | LLM provider abstraction (Anthropic, OpenAI, OpenRouter, Gemini, local, scripted) | ✅ Done — native Gemini adapter planned (P2) |
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
| 15 | Public beta: stable `main` + PR workflow, dogfooding program, agent improvement loop, real-model results | 🚧 In progress — workflow, dogfooding (offline) and improvement loop done; limited REAL results exist (5 models × 2 tasks via OpenCode Go; hard suite; controlled real improvement-loop demonstration — see docs/REAL_MODEL_BENCHMARK.md); awaiting owner merges (PRs #8–#11); routine access needs owner action (T-018) |
| 16 | Portfolio-quality release (screenshots, demo, polished docs) | ⏳ Planned |

## Next up (in order)

1. Owner actions: merge PRs #8 → #9 → #10 → #11 in that order (then update
   #12 onto `main`), rotate the OpenCode Go key, attach the repository to the
   daily routine and disable the duplicate routine (T-018), make `main` the
   default branch.
2. A CI regression gate (fail a pipeline when `bench compare` reports a
   regression or a pass rate drops below a threshold) — planned, not built.
3. Larger real-model runs with repeats, and a real improvement cycle on an
   unconstrained failure (needs budget; T-009b).
4. Public beta checklist and the `v0.2.0` decision (T-015b); limited real
   results now exist.
