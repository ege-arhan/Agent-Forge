# REAL MODEL PROVIDER results

**No real-model results have been recorded yet.**

Reason (2026-09-26): the development environment has no model-provider
credentials (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`,
`GEMINI_API_KEY` are unset) and no local model server, so
`scripts/dogfood.py real` refuses to run. Real-model runs also need an owner
decision on API spend (TASKS.md T-009b).

When they are run, reports appear here as
`<suite>-v<version>/<timestamp>-<agent>-<benchmark-id>.{json,md}`, separate
from the offline results.
