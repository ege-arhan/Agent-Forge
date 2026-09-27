# CONTROLLED IMPROVEMENT-LOOP DEMONSTRATION — results

**REAL MODEL** · Provider: **OpenCode Go** · Model: **DeepSeek V4.1 Flash** (`deepseek-v4.1-flash`). Offline/scripted results are stored separately.

- Date: 2026-09-27T08:42:03+00:00 to 2026-09-27T08:43:55+00:00
- AgentForge: 0.1.0 (commit `0bda883`)
- Endpoint: `https://opencode.ai/zen/go/v1`; authentication: proxy (credential injected by the egress proxy; no key in this process)
- Suite: `dogfood/benchmarks/hard.yaml` v1, tasks: ledger-root-causes
- Baseline constraint (v1): limits.max_steps = 8 (engineer agent: 20)
- Task executions: 2 (limit 2); model-call retries: none; token budget per task: 150000
- Sandbox: docker (python:3.12, network none)
- Secret scan of stored results and logs: clean

| Version | Task | Success | Tests | Score | Tool calls (errors) | Steps | Retries | Duration (s) | Avg model-call latency (ms) | Tokens in/out/total | Cost | Failure | Checks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v1 | ledger-root-causes | no | no | 0.667 | 16 (0) | 8 | 0 | 53.943 | 5857.75 | 24639 / 5071 / 29710 | NOT AVAILABLE | step-limit failure | finished ✗, unit_tests ✓, report_correct ✓, existing_tests_kept ✓, data_and_main_untouched ✓, hidden_edge_cases ✓, regression_test_per_root_cause ✗, names_both_causes ✗ |
| v2 | ledger-root-causes | yes | yes | 1 | 18 (0) | 10 | 0 | 57.666 | 5310.4 | 40733 / 6128 / 46861 | NOT AVAILABLE | — | finished ✓, unit_tests ✓, report_correct ✓, existing_tests_kept ✓, data_and_main_untouched ✓, hidden_edge_cases ✓, regression_test_per_root_cause ✓, names_both_causes ✓ |

## Failure analysis (v1)

- `step_limit`: 1 run(s)
  - ledger-root-causes: The run reached its step limit before finishing. (8 steps used) — max_steps: reached the limit of 8 steps; finished (no_final_answer): run status failed

## Proposal

- `c1` set `limits.max_steps` (applied): 1 failed run(s) stopped at the agent's step limit (8) while the suite allows up to 25 steps for these tasks.

## Comparison: verdict `inconclusive`

- ledger-root-causes: 0/1 -> 1/1 (fixed)
- note: the 95% intervals overlap: run more repeats before concluding that the change helped or hurt

Cost: NOT AVAILABLE (AgentForge does not read billing).
