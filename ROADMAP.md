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
| 10 | GitHub integration (client, tools, issue → draft PR workflow) | ✅ Core done — API endpoints + dashboard page pending |
| 11 | Web dashboard | 🚧 In progress |
| 12 | Observability (structured logs ✅, events/SSE ✅, OpenTelemetry export, metrics endpoint) | 🟡 Partial |
| 13 | Security hardening | 🟡 Partial — see SECURITY.md "planned hardening" |
| 14 | CI/CD and developer experience | 🟡 CI workflows written; Alembic migrations, release automation pending |
| 15 | Public beta | ⏳ Planned |
| 16 | Portfolio-quality release (screenshots, demo, polished docs) | ⏳ Planned |

## Next up (in order)

1. Dashboard (M11): runs list/detail with trace viewer, agents, benchmarks,
   experiments, stats overview.
2. GitHub API endpoints + dashboard page (finish M10).
3. OpenTelemetry trace export and Prometheus-style metrics (M12).
4. Alembic migrations; release workflow; container publishing (M14).
5. Security hardening items (M13), then public beta checklist (M15).
