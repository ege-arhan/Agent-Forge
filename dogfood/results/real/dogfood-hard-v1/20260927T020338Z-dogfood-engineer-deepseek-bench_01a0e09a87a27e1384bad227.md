# Dogfood: hard engineering tasks — REAL MODEL PROVIDER

- Benchmark run: `bench_01a0e09a87a27e1384bad227` (succeeded)
- Suite: `dogfood-hard` version 1
- Agent: `dogfood-engineer-deepseek` v1
- Provider / model: `opencode-go` / `deepseek-v4.1-flash`
- AgentForge: 0.1.0
- Date: 2026-09-27 02:03 UTC, repeats: 1
- Pass rate: 2/2 (100%, 95% CI 0.34-1.00)
- Tokens in/out: 146954 / 15530; estimated cost: n/a; actual cost: n/a

| task | repeat | success | checks passed | tool calls | retries | duration (s) | tokens in/out |
|---|---|---|---|---|---|---|---|
| coupons-feature | 1 | yes | 7/7 | 23 | 0 | 70.556 | 90715 / 7908 |
| ledger-root-causes | 1 | yes | 8/8 | 19 | 0 | 73.994 | 56239 / 7622 |

## Notes

- Values that were not measured are null. actual_cost_usd is always null: AgentForge does not read provider billing; estimated_cost_usd uses the pricing table.
