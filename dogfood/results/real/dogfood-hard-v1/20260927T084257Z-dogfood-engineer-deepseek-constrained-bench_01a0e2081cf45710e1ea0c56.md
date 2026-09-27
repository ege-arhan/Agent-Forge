# Dogfood: hard engineering tasks — REAL MODEL PROVIDER

- Benchmark run: `bench_01a0e2081cf45710e1ea0c56` (succeeded)
- Suite: `dogfood-hard` version 1
- Agent: `dogfood-engineer-deepseek-constrained` v2
- Provider / model: `opencode-go` / `deepseek-v4.1-flash`
- AgentForge: 0.1.0
- Date: 2026-09-27 08:42 UTC, repeats: 1
- Pass rate: 1/1 (100%, 95% CI 0.21-1.00)
- Tokens in/out: 40733 / 6128; estimated cost: n/a; actual cost: n/a

| task | repeat | success | checks passed | tool calls | retries | duration (s) | tokens in/out |
|---|---|---|---|---|---|---|---|
| ledger-root-causes | 1 | yes | 8/8 | 18 | 0 | 57.666 | 40733 / 6128 |

## Notes

- Values that were not measured are null. actual_cost_usd is always null: AgentForge does not read provider billing; estimated_cost_usd uses the pricing table.
