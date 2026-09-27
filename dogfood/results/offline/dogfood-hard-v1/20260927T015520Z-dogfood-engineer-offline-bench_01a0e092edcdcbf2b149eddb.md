# Dogfood: hard engineering tasks — OFFLINE / SCRIPTED PROVIDER

- Benchmark run: `bench_01a0e092edcdcbf2b149eddb` (succeeded)
- Suite: `dogfood-hard` version 1
- Agent: `dogfood-engineer-offline` v1
- Provider / model: `scripted` / `scripted-reference-v1`
- AgentForge: 0.1.0
- Date: 2026-09-27 01:55 UTC, repeats: 1
- Pass rate: 4/4 (100%, 95% CI 0.51-1.00)
- Tokens in/out: n/a / n/a; estimated cost: n/a; actual cost: n/a

| task | repeat | success | checks passed | tool calls | retries | duration (s) | tokens in/out |
|---|---|---|---|---|---|---|---|
| coupons-feature | 1 | yes | 7/7 | 7 | 0 | 0.808 | n/a / n/a |
| ledger-root-causes | 1 | yes | 8/8 | 5 | 0 | 0.484 | n/a / n/a |
| git-regression-hunt | 1 | yes | 9/9 | 4 | 0 | 0.198 | n/a / n/a |
| env-overrides | 1 | yes | 7/7 | 5 | 0 | 0.213 | n/a / n/a |

## Notes

- Values that were not measured are null. actual_cost_usd is always null: AgentForge does not read provider billing; estimated_cost_usd uses the pricing table.
- OFFLINE result: produced by the deterministic scripted provider. It validates the pipeline and the benchmark tasks; it says nothing about any model's capability.
- Token usage was not reported by the provider for some or all runs.
