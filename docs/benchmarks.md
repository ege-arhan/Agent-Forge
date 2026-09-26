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
agentforge experiment run EXPERIMENT.yaml [--json]
```

API: `GET /api/v1/benchmarks/suites`, `POST /api/v1/benchmarks/runs`,
`GET /api/v1/benchmarks/runs[/{id}]`, `POST /api/v1/experiments`,
`GET /api/v1/experiments[/{id}]` (includes the comparison).
