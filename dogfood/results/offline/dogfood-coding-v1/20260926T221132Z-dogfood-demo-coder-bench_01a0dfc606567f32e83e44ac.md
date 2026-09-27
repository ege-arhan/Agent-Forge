# Dogfood: coding — OFFLINE / SCRIPTED PROVIDER

- Benchmark run: `bench_01a0dfc606567f32e83e44ac` (succeeded)
- Suite: `dogfood-coding` version 1
- Agent: `dogfood-demo-coder` v1
- Provider / model: `scripted` / `scripted-reference-v1`
- AgentForge: 0.1.0
- Date: 2026-09-26 22:11 UTC, repeats: 3
- Pass rate: 0/6 (0%, 95% CI 0.00-0.39)
- Tokens in/out: n/a / n/a; estimated cost: n/a; actual cost: n/a

| task | repeat | success | checks passed | tool calls | retries | duration (s) | tokens in/out |
|---|---|---|---|---|---|---|---|
| implement-slugify | 1 | no | 3/4 | 3 | 0 | 0.104 | n/a / n/a |
| implement-slugify | 2 | no | 3/4 | 3 | 0 | 0.091 | n/a / n/a |
| implement-slugify | 3 | no | 3/4 | 3 | 0 | 0.093 | n/a / n/a |
| add-cli-flag | 1 | no | 4/5 | 3 | 0 | 0.266 | n/a / n/a |
| add-cli-flag | 2 | no | 4/5 | 3 | 0 | 0.24 | n/a / n/a |
| add-cli-flag | 3 | no | 4/5 | 3 | 0 | 0.246 | n/a / n/a |

## Failures

- `implement-slugify` #1: max_steps: reached the limit of 3 steps
- `implement-slugify` #2: max_steps: reached the limit of 3 steps
- `implement-slugify` #3: max_steps: reached the limit of 3 steps
- `add-cli-flag` #1: max_steps: reached the limit of 3 steps
- `add-cli-flag` #2: max_steps: reached the limit of 3 steps
- `add-cli-flag` #3: max_steps: reached the limit of 3 steps

## Notes

- Values that were not measured are null. actual_cost_usd is always null: AgentForge does not read provider billing; estimated_cost_usd uses the pricing table.
- OFFLINE result: produced by the deterministic scripted provider. It validates the pipeline and the benchmark tasks; it says nothing about any model's capability.
- Token usage was not reported by the provider for some or all runs.
