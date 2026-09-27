# Dogfood: data analysis — OFFLINE / SCRIPTED PROVIDER

- Benchmark run: `bench_01a0dfc602d5803d33f65f97` (succeeded)
- Suite: `dogfood-data` version 1
- Agent: `dogfood-data-analysis-offline` v1
- Provider / model: `scripted` / `scripted-reference-v1`
- AgentForge: 0.1.0
- Date: 2026-09-26 22:11 UTC, repeats: 1
- Pass rate: 2/2 (100%, 95% CI 0.34-1.00)
- Tokens in/out: n/a / n/a; estimated cost: n/a; actual cost: n/a

| task | repeat | success | checks passed | tool calls | retries | duration (s) | tokens in/out |
|---|---|---|---|---|---|---|---|
| sales-by-region | 1 | yes | 3/3 | 4 | 0 | 0.09 | n/a / n/a |
| service-error-rates | 1 | yes | 3/3 | 3 | 0 | 0.086 | n/a / n/a |

## Notes

- Values that were not measured are null. actual_cost_usd is always null: AgentForge does not read provider billing; estimated_cost_usd uses the pricing table.
- OFFLINE result: produced by the deterministic scripted provider. It validates the pipeline and the benchmark tasks; it says nothing about any model's capability.
- Token usage was not reported by the provider for some or all runs.
