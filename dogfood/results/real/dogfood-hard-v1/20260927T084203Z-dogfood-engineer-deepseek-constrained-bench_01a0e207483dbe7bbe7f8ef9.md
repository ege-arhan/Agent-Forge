# Dogfood: hard engineering tasks — REAL MODEL PROVIDER

- Benchmark run: `bench_01a0e207483dbe7bbe7f8ef9` (succeeded)
- Suite: `dogfood-hard` version 1
- Agent: `dogfood-engineer-deepseek-constrained` v1
- Provider / model: `opencode-go` / `deepseek-v4.1-flash`
- AgentForge: 0.1.0
- Date: 2026-09-27 08:42 UTC, repeats: 1
- Pass rate: 0/1 (0%, 95% CI 0.00-0.79)
- Tokens in/out: 24639 / 5071; estimated cost: n/a; actual cost: n/a

| task | repeat | success | checks passed | tool calls | retries | duration (s) | tokens in/out |
|---|---|---|---|---|---|---|---|
| ledger-root-causes | 1 | no | 5/8 | 16 | 0 | 53.943 | 24639 / 5071 |

## Failures

- `ledger-root-causes` #1: max_steps: reached the limit of 8 steps

## Notes

- Values that were not measured are null. actual_cost_usd is always null: AgentForge does not read provider billing; estimated_cost_usd uses the pricing table.
