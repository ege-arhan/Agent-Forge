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
| 15 | Public beta / v0.2.0: stable `main` + PR workflow, dogfooding program, agent improvement loop, human approval gate, CI regression gate, limited real-model validation | ✅ Done in the release branch (PR #11, which also carries #12) — awaiting the owner's merges and the `v0.2.0` tag; see `docs/RELEASE_CHECKLIST.md` |
| 16 | Portfolio-quality release (screenshots, demo, polished docs) | ⏳ Planned |

The project is in **feature freeze** after v0.2.0: fixes, tests, security and
documentation only, until the owner starts milestone 16 or a future-work item.

## Next up (owner, in order)

1. Merge PRs #8 → #9 → #10 → #11 (PR #11 contains PR #12's commit, merged with
   its conflicts resolved; #12 then shows as merged).
2. Make `main` the default branch and protect it; push the `v0.2.0` tag on
   `main` (the release workflow drafts the release).
3. Rotate the OpenCode Go key; disable the old "Agent Forge" routine and attach
   the repository to "AgentForge daily development" (T-018).

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
- Also planned: native Gemini adapter (T-002b), vector memory (T-006b),
  streaming output (T-003b), distributed execution (T-015), dashboard
  enhancements (T-011b).
