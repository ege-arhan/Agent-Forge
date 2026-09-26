# Dogfood: coding — OFFLINE / SCRIPTED PROVIDER

- Benchmark run: `bench_01a0dfc5ff89d29beb8e1bf5` (succeeded)
- Suite: `dogfood-coding` version 1
- Agent: `dogfood-coding-offline` v1
- Provider / model: `scripted` / `scripted-reference-v1`
- AgentForge: 0.1.0
- Date: 2026-09-26 22:11 UTC, repeats: 1
- Pass rate: 2/2 (100%, 95% CI 0.34-1.00)
- Tokens in/out: n/a / n/a; estimated cost: n/a; actual cost: n/a

| task | repeat | success | checks passed | tool calls | retries | duration (s) | tokens in/out |
|---|---|---|---|---|---|---|---|
| implement-slugify | 1 | yes | 4/4 | 4 | 0 | 0.144 | n/a / n/a |
| add-cli-flag | 1 | yes | 5/5 | 3 | 0 | 0.311 | n/a / n/a |

## Notes

- Values that were not measured are null. actual_cost_usd is always null: AgentForge does not read provider billing; estimated_cost_usd uses the pricing table.
- OFFLINE result: produced by the deterministic scripted provider. It validates the pipeline and the benchmark tasks; it says nothing about any model's capability.
- Token usage was not reported by the provider for some or all runs.
