# CI regression gate

`agentforge bench gate` turns a benchmark comparison into a CI decision:

```
agent change / PR ─► benchmark ─► evaluation ─► compare with the baseline ─► regression?
                                                                              ├─ no  → exit 0 (CI passes)
                                                                              └─ yes → exit 1 (CI fails)
```

It evaluates nothing itself. Pass/fail and scores come from the suite's
evaluators (the same runs `bench run` records), failure categories from the
[failure analysis](improvement.md#failure-categories).

## Usage

```bash
# 1. Once: benchmark the accepted agent and commit its report as the baseline.
agentforge bench run SUITE.yaml -a AGENT.yaml --json            # prints the run, incl. "id"
agentforge bench report BENCH_ID --out baselines/                # writes baselines/<class>/<suite>-v<n>/<...>.json

# 2. In CI, for every change: benchmark the candidate, then gate it.
agentforge bench run SUITE.yaml -a AGENT.yaml --json > candidate.json
agentforge bench gate --baseline baselines/offline/suite-v1/<...>.json \
                      --candidate "$(python3 -c 'import json; print(json.load(open("candidate.json"))["id"])')"
```

`--baseline` and `--candidate` each take a **report JSON file** (from `bench
report --out` or `bench run --report`) or the id of a **stored benchmark run**
in the configured database. The baseline must be given explicitly; there is no
default and nothing is inferred.

Options:

| Option | Default | Meaning |
|---|---|---|
| `--max-pass-rate-drop F` | `0` | allowed drop of the overall pass rate (absolute, 0–1) |
| `--max-task-pass-rate-drop F` | `0` | allowed drop of any single task's pass rate |
| `--max-mean-score-drop F` | `0` | allowed drop of the mean evaluation score |
| `--min-pass-rate F` | none | absolute floor for the candidate's pass rate |
| `--json` | off | print the result as JSON instead of text |
| `--output FILE` | none | also write the JSON result to `FILE` (e.g. a CI artifact) |

The defaults are conservative: any drop fails. Loosen them only when a suite is
known to be noisy (real models, few repeats) — and prefer more repeats.

API: `GET /api/v1/benchmarks/gate?baseline=ID&candidate=ID[&max_pass_rate_drop=…]`
applies the same rules to two stored runs. The dashboard shows the gate result
(default thresholds) for every evaluated improvement cycle.

## Verdicts and exit codes

| Exit | Verdict | When |
|---|---|---|
| `0` | `pass` | the two are comparable and no threshold is violated |
| `1` | `regression` | the two are comparable and at least one threshold is violated |
| `2` | `error` | the gate cannot decide — never treated as a pass |

`error` covers:

- a baseline or candidate that does not exist, is not a valid report, or has no runs;
- different suites (id or version), different task definitions (suite digests
  differ), or different task sets;
- different result classes — offline (scripted) results are never compared
  with real-model results;
- a benchmark that did not finish;
- any run, in either benchmark, that failed for an **infrastructure** reason
  (failure category `setup`, `internal`, `cancelled` or `missing_record`): such
  a run is not a valid evaluation, even if the baseline failed the same task.

Thresholds are only applied to a comparable pair. The output is deterministic
(sorted tasks, no timestamps); the JSON result lists `errors`, `regressions`,
`notes`, both sides' pass rates and mean scores, and per-task counts.

## Reports from older versions

Reports written before 0.2.0 have no `suite_digest` and no per-run
`failure_category`. They are still accepted: suites are then compared by id
and version only, failed runs without a category count as agent failures
(`missing`/`cancelled` runs are still infrastructure errors), and the result
carries a note saying so.

## GitHub Actions

[`.github/workflows/agentforge-regression.yml`](../.github/workflows/agentforge-regression.yml)
is a working example: on pull requests it benchmarks the offline reference
coding agent (no API key, no model calls) and gates it against
[`examples/ci/baselines/dogfood-coding-offline.json`](../examples/ci/baselines/dogfood-coding-offline.json).
For a real-model agent, give the job the provider key as a GitHub Actions
secret (never a file in the repository) and commit a baseline produced by that
agent. The workflow never merges anything.

## Limitations

- One run per task makes pass rates coarse (0 or 1 per task); with real models
  the same config can pass or fail across runs. Use `-r N` repeats for both
  baseline and candidate, and thresholds that match the suite's noise.
- The gate compares against one baseline; it does not track trends across many
  runs.
