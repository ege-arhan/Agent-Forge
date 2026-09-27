# LIMITED REAL-MODEL IMPROVEMENT EXPERIMENT — results

**REAL MODEL** · Provider: **OpenCode Go** · Model: **DeepSeek V4.1 Flash** (`deepseek-v4.1-flash`). Offline/scripted results are stored separately.

- Date: 2026-09-27T02:03:38+00:00 to 2026-09-27T02:06:03+00:00
- AgentForge: 0.1.0 (commit `f8ae4e4`)
- Endpoint: `https://opencode.ai/zen/go/v1`; authentication: proxy (credential injected by the egress proxy; no key in this process)
- Suite: `dogfood/benchmarks/hard.yaml` v1, tasks: coupons-feature, ledger-root-causes
- Task executions: 2 (limit 4); model-call retries: none; token budget per task: 150000
- Sandbox: docker (python:3.12, network none)
- Secret scan of stored results and logs: clean

| Version | Task | Success | Tests | Score | Tool calls (errors) | Steps | Retries | Duration (s) | Avg model-call latency (ms) | Tokens in/out/total | Cost | Failure | Checks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v1 | coupons-feature | yes | yes | 1 | 23 (0) | 15 | 0 | 70.556 | 4424.067 | 90715 / 7908 / 98623 | NOT AVAILABLE | — | finished ✓, unit_tests ✓, existing_tests_untouched ✓, coupon_tests_added ✓, hidden_api ✓, hidden_cli ✓, ran_commands ✓ |
| v1 | ledger-root-causes | yes | yes | 1 | 19 (0) | 13 | 0 | 73.994 | 5339.923 | 56239 / 7622 / 63861 | NOT AVAILABLE | — | finished ✓, unit_tests ✓, report_correct ✓, existing_tests_kept ✓, data_and_main_untouched ✓, hidden_edge_cases ✓, regression_test_per_root_cause ✓, names_both_causes ✓ |

**Stopped after v1:** v1 passed every task: the tasks were not difficult enough for this model to show an improvement, so no improvement was attempted

Cost: NOT AVAILABLE (AgentForge does not read billing).
