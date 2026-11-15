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
default and nothing is inferred. `--baseline` may be repeated to
[pool several accepted runs](#pooled-baselines).

Options:

| Option | Default | Meaning |
|---|---|---|
| `--max-pass-rate-drop F` | `0` | allowed drop of the overall pass rate (absolute, 0–1) |
| `--max-task-pass-rate-drop F` | `0` | allowed drop of any single task's pass rate |
| `--max-mean-score-drop F` | `0` | allowed drop of the mean evaluation score |
| `--min-pass-rate F` | none | absolute floor for the candidate's pass rate |
| `--max-token-increase F` | off | opt-in token budget: allowed relative increase of the tokens one pass over the suite uses (`0.25` = +25%) |
| `--max-duration-increase F` | off | opt-in latency budget: allowed relative increase of mean run duration (wall-clock is noisy; use a generous value) |
| `--min-repeats N` | off | opt-in: every task needs at least `N` runs in the baseline and in the candidate, otherwise exit 2 |
| `--max-check-pass-rate-drop F` | off | opt-in: allowed drop of any single check's pass rate within a task |
| `--fail-on-category CATEGORY` | off | opt-in, repeatable: a candidate run that failed with this [failure category](improvement.md#failure-categories) is always a regression |
| `--json` | off | print the result as JSON instead of text |
| `--output FILE` | none | also write the JSON result to `FILE` (e.g. a CI artifact) |

The budgets only apply when set. If a budget is set but any run of either report
has no recorded usage (e.g. the scripted provider reports no tokens), or the
baseline value is zero, the gate cannot decide and exits 2 — it never treats
missing data as a pass. Usage is averaged over each task's repeats first, so a
report with three repeats is not charged three times the usage of a report
with one. The API accepts the same options as query parameters
(`fail_on_category` and `baseline` may be repeated).

### Opt-in policies

- **Required repeats** (`--min-repeats N`). One run per task says little about
  a model that passes the task only some of the time. With this option the gate
  refuses to decide (exit 2) unless every task has at least `N` runs on both
  sides. A pooled baseline counts all its reports' runs.
- **Per-check threshold** (`--max-check-pass-rate-drop F`). A task can keep
  passing while one of its checks starts failing — a check that is not
  `required`, with the score unchanged or the score threshold loosened. This
  compares the pass rate of every named check of the baseline, task by task. A
  run that did not record a check (it stopped before evaluation) did not pass
  it; a check only the candidate has is ignored.
- **Categories that are never tolerated** (`--fail-on-category CATEGORY`).
  When the pass-rate thresholds are loosened for a noisy suite, some kinds of
  failure may still be unacceptable — e.g. `timeout`, `token_budget` or
  `llm_refusal`. Any candidate run that failed with a listed category is a
  regression, whatever the baseline did. Unknown category names are rejected
  (exit 2; HTTP 422). Reports written before 0.2.0 have no categories, so
  this policy cannot see their failures.

### Pooled baselines

```bash
agentforge bench gate --baseline accepted/run-1.json --baseline accepted/run-2.json \
                      --baseline accepted/run-3.json --candidate "$BENCH_ID" --min-repeats 3
```

Give `--baseline` several times to compare against the last accepted runs
instead of a single one. Their runs are pooled: a task that passed in 2 of 3
accepted runs has a baseline pass rate of 0.67, so one lucky (or unlucky)
baseline run no longer decides the verdict. Every pooled report must be
comparable with the candidate (same suite, task definitions, result class and
task set; finished; no infrastructure failures) — otherwise the gate exits 2
and names the report. The baseline line of the result shows the last report
given; the result's notes say how many reports and runs were pooled and
whether they came from different agent versions or models. This is a pooled
rate, not a trend analysis: the gate does not weight newer runs or fit a
slope, and choosing which accepted runs to pass in is up to the CI job.

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
- A pooled baseline averages the accepted runs it is given; the gate does not
  store accepted runs, pick them, weight them by age or detect a slow drift
  that stays inside the thresholds at every step.
- No statistical test is applied: thresholds are compared with observed rates.
  `--min-repeats` only makes sure the rates rest on enough runs.
