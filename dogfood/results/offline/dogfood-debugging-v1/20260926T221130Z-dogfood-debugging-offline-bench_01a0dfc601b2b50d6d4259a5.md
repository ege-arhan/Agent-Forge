# Dogfood: debugging — OFFLINE / SCRIPTED PROVIDER

- Benchmark run: `bench_01a0dfc601b2b50d6d4259a5` (succeeded)
- Suite: `dogfood-debugging` version 1
- Agent: `dogfood-debugging-offline` v1
- Provider / model: `scripted` / `scripted-reference-v1`
- AgentForge: 0.1.0
- Date: 2026-09-26 22:11 UTC, repeats: 1
- Pass rate: 2/2 (100%, 95% CI 0.34-1.00)
- Tokens in/out: n/a / n/a; estimated cost: n/a; actual cost: n/a

| task | repeat | success | checks passed | tool calls | retries | duration (s) | tokens in/out |
|---|---|---|---|---|---|---|---|
| pagination-off-by-one | 1 | yes | 5/5 | 5 | 0 | 0.115 | n/a / n/a |
| shared-mutable-default | 1 | yes | 4/4 | 4 | 0 | 0.14 | n/a / n/a |

## Notes

- Values that were not measured are null. actual_cost_usd is always null: AgentForge does not read provider billing; estimated_cost_usd uses the pricing table.
- OFFLINE result: produced by the deterministic scripted provider. It validates the pipeline and the benchmark tasks; it says nothing about any model's capability.
- Token usage was not reported by the provider for some or all runs.
