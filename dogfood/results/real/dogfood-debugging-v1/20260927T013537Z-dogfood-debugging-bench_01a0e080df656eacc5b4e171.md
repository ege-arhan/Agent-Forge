# Dogfood: debugging — REAL MODEL PROVIDER

- Benchmark run: `bench_01a0e080df656eacc5b4e171` (succeeded)
- Suite: `dogfood-debugging` version 1
- Agent: `dogfood-debugging`
- Provider / model: `opencode-go` / `glm-5.3-flash`
- AgentForge: 0.1.0
- Date: 2026-09-27 01:35 UTC, repeats: 1
- Pass rate: 1/1 (100%, 95% CI 0.21-1.00)
- Tokens in/out: 10397 / 1155; estimated cost: n/a; actual cost: n/a

| task | repeat | success | checks passed | tool calls | retries | duration (s) | tokens in/out |
|---|---|---|---|---|---|---|---|
| pagination-off-by-one | 1 | yes | 5/5 | 8 | 0 | 9.186 | 10397 / 1155 |

## Notes

- Values that were not measured are null. actual_cost_usd is always null: AgentForge does not read provider billing; estimated_cost_usd uses the pricing table.
