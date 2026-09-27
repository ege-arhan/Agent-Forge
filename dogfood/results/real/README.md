# REAL MODEL PROVIDER results

**No real-model results have been recorded yet.**

2026-09-27: the Limited Real-Model Validation with five OpenCode Go models is
prepared (`scripts/real_model_validation.py`, see
[docs/REAL_MODEL_BENCHMARK.md](../../../docs/REAL_MODEL_BENCHMARK.md)) but could
not run: the environment's network policy blocks `opencode.ai`. No model was
called.

Reason (2026-09-26): the development environment has no model-provider
credentials (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`,
`GEMINI_API_KEY` are unset) and no local model server, so
`scripts/dogfood.py real` refuses to run. Real-model runs also need an owner
decision on API spend (TASKS.md T-009b).

When they are run, reports appear here as
`<suite>-v<version>/<timestamp>-<agent>-<benchmark-id>.{json,md}`, separate
from the offline results.
