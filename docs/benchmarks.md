# Benchmarks and experiments

## Suite format

```yaml
id: starter                  # lowercase id
name: Starter engineering tasks
version: "1"
repeats: 3                   # default repeats (CLI/API can override)
defaults:
  timeout_seconds: 300       # caps per task
  max_steps: 15
tasks:
  - id: fix-failing-test
    goal: The tests in test_calc.py fail. Fix calc.py ...
    setup:
      files: {calc.py: "...", test_calc.py: "..."}   # initial workspace
      commands: ["pip install -e ."]                 # run in the sandbox first
      git_init: false                                # init repo + commit setup
    allowed_tools: [filesystem, terminal]            # replaces the agent's tools
    expected_behavior: Run tests, locate bug, fix, re-run.
    evaluators:                                      # success criteria
      - {type: command, command: python3 test_calc.py}
    timeout_seconds: 120
    max_steps: 12
```

Semantics:

- Each task × repeat is a normal, fully recorded run in a fresh workspace,
  labelled `benchmark`, `task`, `repeat` (and `variant` in experiments).
- `allowed_tools` replaces the agent's tool list so every agent faces the
  same environment. Omit it to use the agent's own tools.
- Task/suite `timeout_seconds` and `max_steps` are **caps**: an agent with a
  tighter limit keeps it.
- Setup failures are recorded as failed results (not silently skipped).
- Failed or timed-out runs are still evaluated against the workspace.

## Results

Per benchmark run: every task result (status, passed, score, duration, steps,
tool calls, tool success rate, LLM retries, tokens, cost, error) and a summary:

- pass rate with a 95% **Wilson score interval**,
- mean score and sample standard deviation,
- mean duration, mean steps, mean tool success rate,
- total tokens and total cost (`null` unless every run's cost is known),
- per-task pass rate, mean score and spread.

### Result classes and reports

Every benchmark run has a `result_class`: `offline` for the scripted provider,
`real` for model providers. It is derived from the agent config, and offline
and real results are never mixed: filters (`result_class=`), reports and the
dashboard keep them apart, and comparisons across classes are refused.

`agentforge bench report BENCH_ID [--out DIR]` (or `bench run … --report DIR`,
`GET /benchmarks/runs/{id}/report`) produces a publication record per task
run: success, each check's result, tool calls and errors, duration, LLM and
evaluation retries, token usage (`null` when the provider reported none),
estimated cost from the pricing table and `actual_cost_usd` (always `null`:
AgentForge does not read provider billing). Saved reports go to
`DIR/<offline|real>/<suite>-v<version>/`.

`bench run --save-agent` stores the agent (a new version only if the config
changed) and links the benchmark to that version, which the
[improvement loop](improvement.md) builds on. `agentforge bench compare A B`
compares two runs of the same suite version.

## Dogfooding suites

`dogfood/benchmarks/` holds the suites AgentForge uses to validate itself
(coding, debugging, data analysis, security analysis, GitHub issue solving):
see [dogfood/README.md](../dogfood/README.md). They are discovered by default
alongside `examples/benchmarks` (`AGENTFORGE_BENCHMARKS_DIR` accepts several
directories separated by `:`).

## Experiments

```yaml
name: claude-model-comparison
benchmark: ../benchmarks/starter.yaml       # relative to this file
base_agent: ../agents/anthropic-coder.yaml  # or an inline config
repeats: 3
task_ids: [fix-failing-test]                # optional subset
variants:
  - name: opus-react                        # first variant = baseline
  - name: sonnet-react
    overrides: {model: {model: claude-sonnet-5}}
  - name: opus-plan-execute
    overrides: {planner: {strategy: plan_execute}}
```

Overrides are deep-merged into the base config and validated before anything
runs. The comparison lists, per variant: runs, pass rate, 95% CI, delta vs.
the baseline, mean score, duration, steps, cost and per-task pass rates.
Each variant stores its provider/model, full config and environment
(AgentForge version, Python, platform, sandbox).

## Interpreting results responsibly

- Small suites and few repeats produce wide intervals; overlapping intervals
  mean the data does not distinguish the variants.
- Results are specific to the suite, prompts, tools, limits and sandbox used;
  they are not general model rankings.
- The scripted demo agent exists to test the pipeline. Its numbers measure
  nothing about models.

## Commands

```bash
agentforge bench list examples/benchmarks
agentforge bench run SUITE.yaml -a AGENT.yaml [-r REPEATS] [-t TASK]... [-c CONCURRENCY] [--json]
                     [--save-agent] [--report DIR]
agentforge bench report BENCH_ID [--out DIR] [--json]
agentforge bench compare BASELINE_ID CANDIDATE_ID [--json]
agentforge bench gate --baseline REPORT_OR_ID --candidate REPORT_OR_ID [thresholds] [--json] [--output FILE]   # CI gate, see regression-gate.md
agentforge experiment run EXPERIMENT.yaml [--json]
```

API: `GET /api/v1/benchmarks/suites`, `POST /api/v1/benchmarks/runs`,
`GET /api/v1/benchmarks/runs[/{id}]`, `GET /api/v1/benchmarks/runs/{id}/report`,
`GET /api/v1/benchmarks/runs/{id}/analysis`, `GET /api/v1/benchmarks/compare`,
`POST /api/v1/experiments`, `GET /api/v1/experiments[/{id}]` (includes the
comparison).
