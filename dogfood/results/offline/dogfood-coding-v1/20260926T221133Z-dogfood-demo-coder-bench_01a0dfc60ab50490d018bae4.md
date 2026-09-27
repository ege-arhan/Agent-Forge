# Dogfood: coding — OFFLINE / SCRIPTED PROVIDER

- Benchmark run: `bench_01a0dfc60ab50490d018bae4` (succeeded)
- Suite: `dogfood-coding` version 1
- Agent: `dogfood-demo-coder` v2
- Provider / model: `scripted` / `scripted-reference-v1`
- AgentForge: 0.1.0
- Date: 2026-09-26 22:11 UTC, repeats: 3
- Pass rate: 6/6 (100%, 95% CI 0.61-1.00)
- Tokens in/out: n/a / n/a; estimated cost: n/a; actual cost: n/a

| task | repeat | success | checks passed | tool calls | retries | duration (s) | tokens in/out |
|---|---|---|---|---|---|---|---|
| implement-slugify | 1 | yes | 4/4 | 4 | 0 | 0.122 | n/a / n/a |
| implement-slugify | 2 | yes | 4/4 | 4 | 0 | 0.131 | n/a / n/a |
| implement-slugify | 3 | yes | 4/4 | 4 | 0 | 0.127 | n/a / n/a |
| add-cli-flag | 1 | yes | 5/5 | 3 | 0 | 0.252 | n/a / n/a |
| add-cli-flag | 2 | yes | 5/5 | 3 | 0 | 0.249 | n/a / n/a |
| add-cli-flag | 3 | yes | 5/5 | 3 | 0 | 0.251 | n/a / n/a |

## Notes

- Values that were not measured are null. actual_cost_usd is always null: AgentForge does not read provider billing; estimated_cost_usd uses the pricing table.
- OFFLINE result: produced by the deterministic scripted provider. It validates the pipeline and the benchmark tasks; it says nothing about any model's capability.
- Token usage was not reported by the provider for some or all runs.
