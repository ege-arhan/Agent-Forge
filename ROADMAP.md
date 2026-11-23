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
| 6 | Memory (context compaction, persistent agent memory, memory tools) | ✅ Done — vector and hybrid search (T-006b) implemented, awaiting review |
| 7 | Evaluation engine (built-in + custom + LLM judge, metrics) | ✅ Done |
| 8 | Benchmark engine (suites, repeats, statistics, storage) | ✅ Done |
| 9 | Experiment tracking (variants, comparison, storage) | ✅ Done |
| 10 | GitHub integration (client, tools, issue → draft PR workflow, API, dashboard) | ✅ Done |
| 11 | Web dashboard | ✅ Done — enhancements tracked in T-011b |
| 12 | Observability (structured logs, events/SSE, OpenTelemetry traces, Prometheus metrics) | ✅ Done |
| 13 | Security hardening (API policy, limits, audit, sandbox egress control, gVisor option) | ✅ Done — see SECURITY.md limitations |
| 14 | CI/CD and developer experience (CI, security scans, migrations, release workflow) | ✅ Done |
| 15 | Public beta / v0.2.0: stable `main` + PR workflow, dogfooding program, agent improvement loop, human approval gate, CI regression gate, limited real-model validation | ✅ Done and released — PRs #8–#12 merged, `main` is the default branch, `v0.2.0` tagged and published (verified 2026-09-28) |
| 16 | Portfolio-quality release (screenshots, demo, polished docs) | 🚧 Implemented, awaiting the owner's review and merges — offline tour (PR #37), reproducible screenshots, docs index and README pass (PR #38), walk-through recording and dashboard polish (PR #39); stacked in that order (T-021) |

v0.2.0 is released. No milestone after 16 is defined yet: once the open pull
requests are merged, the next work comes from the future-work list below and
the owner's priorities. Two future-work items are already implemented in
pull requests that await review: the native Gemini adapter (T-002b) and the
regression gate's additional policies (T-019b: token and latency budgets,
required repeats, per-check thresholds, intolerable failure categories,
pooled baselines). A third, the rule-based trace-level failure diagnosis
(T-020), is implemented in PR #42, stacked on those. A fourth, streaming
model output with a live preview in the CLI and the dashboard (T-003b, and
the SSE part of T-011b), is implemented in PR #43 and reviewed, fixed and
stacked on the others in PR #44. The dashboard's run comparison view (another
part of T-011b) is implemented in PR #45, stacked on #44, and the per-day
activity charts (also T-011b) in PR #46, stacked on #45; YAML import in the
agent form (also T-011b) is in PR #48, stacked on #46, and the dashboard's
component tests (the last part of T-011b) are in PR #49, stacked on #48. A fifth
future-work item, vector and hybrid memory search (T-006b), is implemented
in a pull request stacked on #49. `docs/STATUS.md` lists the
open pull requests and the order to merge them in.

## Next up (owner)

- Rotate the OpenCode Go key; disable the old "Agent Forge" routine and attach
  the repository to "AgentForge daily development" (T-018) — session-side
  code cannot verify or change either from here.

## Future work (not started; not part of v0.2.0)

- Stronger benchmark suites: larger, SWE-style tasks with harder hidden checks
  (T-008b).
- More sophisticated improvement proposals: an optional LLM-assisted proposer
  within the same allowlist (T-017b).
- Broader model evaluations: more tasks, repeats and models, and a real
  improvement cycle on an unconstrained failure; needs a budget (T-009c).
- Also planned: distributed execution (T-015). Blocked on credentials: live
  checks of the Gemini adapter (T-002c) and of the OpenAI-compatible embedder
  (T-006c).
