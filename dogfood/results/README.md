# Dogfooding results

OFFLINE and REAL results live in separate directories and are never combined
or compared. Each report is JSON (machine-readable, schema_version 1) plus a
Markdown rendering. See [`../README.md`](../README.md) for the method.

## REAL MODEL PROVIDER

Not run yet — no provider credentials in the development environment
(see [`real/README.md`](real/README.md)). No real-model numbers exist.

## OFFLINE / SCRIPTED PROVIDER (2026-09-26, AgentForge 0.1.0, suites v1)

These validate the benchmark tasks and the pipeline. They are **not** model
performance.

| Suite | Agent (scripted reference) | Passed |
|---|---|---|
| dogfood-coding@1 | dogfood-coding-offline v1 | 2/2 |
| dogfood-debugging@1 | dogfood-debugging-offline v1 | 2/2 |
| dogfood-data@1 | dogfood-data-analysis-offline v1 | 2/2 |
| dogfood-security@1 | dogfood-security-analysis-offline v1 | 2/2 |
| dogfood-issues@1 | dogfood-github-issue-solver-offline v1 | 2/2 |

The same reference agents were also run in the hardened Docker sandbox
(`python:3.12-slim`, no network) for the four suites that do not need git:
8/8 passed. The `agentforge-sandbox` image (with git) could not be built in the
development environment (Debian mirrors blocked), so `dogfood-issues` was
verified with the local sandbox only.

Improvement-loop demo (mechanics only): `dogfood-demo-coder` v1 0/6 →
proposal `limits.max_steps: 3 → 20` → v2 6/6 on dogfood-coding@1 (3 repeats),
verdict "improved". Deterministic replays: the interval statistics describe
the pipeline, not a model. Record:
[`offline/improvement-demo/`](offline/improvement-demo).
