# REAL MODEL PROVIDER results

Kept separate from `../offline/` (scripted reference agents); never merged.

## LIMITED REAL-MODEL VALIDATION (2026-09-27)

Provider: OpenCode Go. Five models × two existing tasks, one run each, 10 task
executions: `limited-validation-20260927T013310Z/summary.{json,md}` plus one
report per task in `dogfood-coding-v1/` and `dogfood-debugging-v1/`.
Method, results and limitations:
[docs/REAL_MODEL_BENCHMARK.md](../../../docs/REAL_MODEL_BENCHMARK.md).

## LIMITED REAL-MODEL IMPROVEMENT EXPERIMENT (2026-09-27)

Provider: OpenCode Go, model `deepseek-v4.1-flash`, agent
`dogfood-engineer-deepseek` v1 on two `dogfood-hard` tasks: both passed, so no
improvement was attempted and there is no v2.
`improvement-20260927T020338Z/summary.{json,md}` and
`dogfood-hard-v1/`.

## Controlled improvement-loop demonstration (2026-09-27)

Same model, `ledger-root-causes` only: agent
`dogfood-engineer-deepseek-constrained` v1 (`limits.max_steps: 8`) failed at the
step limit; v2 (`limits.max_steps: 25`, proposed by the loop) passed.
`improvement-demo-20260927T084203Z/summary.{json,md}` and
`dogfood-hard-v1/`. A controlled demonstration, not evidence of model learning.

Reports are named `<suite>-v<version>/<timestamp>-<suite>-<benchmark-id>.{json,md}`.
