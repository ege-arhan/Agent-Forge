# AgentForge dogfooding program

AgentForge is validated by using it on itself: five realistic agents, each with
reproducible benchmark tasks and machine-checkable evaluation criteria, run
through the same pipeline as any user's agent (runtime → tools → sandbox →
evaluation → storage → failure analysis → improvement loop → dashboard).

## Results are split into two classes that are never mixed

| Class | Produced by | What it shows | Where |
|---|---|---|---|
| **OFFLINE / SCRIPTED PROVIDER** | `dogfood/agents/offline/*.yaml` (scripted provider replaying reference solutions) | Each task is solvable, its checks accept a correct solution and reject the untouched initial state, and the AgentForge pipeline works. **Nothing about any model.** | [`results/offline/`](results/offline) |
| **REAL MODEL PROVIDER** | `dogfood/agents/*.yaml` with a real provider and credentials | How that model + configuration performs on these tasks | [`results/real/`](results/real) |

The separation is enforced in code, not only by convention:
`BenchmarkRun.result_class` is derived from the agent's provider (it cannot be
set by a caller), reports are written under `results/<class>/`, comparisons
between an offline and a real run are refused, and improvement proposals cannot
change the provider.

## Agents and tasks (suite collection "dogfood", version 1)

| Agent | Real-model config | Suite | Tasks |
|---|---|---|---|
| Coding Agent | [`agents/coding.yaml`](agents/coding.yaml) | [`benchmarks/coding.yaml`](benchmarks/coding.yaml) (`dogfood-coding`) | `implement-slugify` (implement a function from its docstring), `add-cli-flag` (extend a CLI without changing default behaviour) |
| Debugging Agent | [`agents/debugging.yaml`](agents/debugging.yaml) | [`benchmarks/debugging.yaml`](benchmarks/debugging.yaml) (`dogfood-debugging`) | `pagination-off-by-one` (two root causes), `shared-mutable-default` |
| Data Analysis Agent | [`agents/data-analysis.yaml`](agents/data-analysis.yaml) | [`benchmarks/data-analysis.yaml`](benchmarks/data-analysis.yaml) (`dogfood-data`) | `sales-by-region` (CSV aggregation to JSON), `service-error-rates` (log parsing, malformed lines) |
| Security Analysis Agent | [`agents/security-analysis.yaml`](agents/security-analysis.yaml) | [`benchmarks/security.yaml`](benchmarks/security.yaml) (`dogfood-security`) | `sql-injection` (report CWE-89 and fix), `hardcoded-credential` (report CWE-798, move to env var) |
| GitHub Issue Solver | [`agents/github-issue-solver.yaml`](agents/github-issue-solver.yaml) | [`benchmarks/issues.yaml`](benchmarks/issues.yaml) (`dogfood-issues`) | `issue-7-leap-year` (bug fix), `issue-12-feature` (feature), each in a git repo with `ISSUE.md` and `CONTRIBUTING.md` |
| Engineering Agent (hard suite) | [`agents/engineer.yaml`](agents/engineer.yaml) | [`benchmarks/hard.yaml`](benchmarks/hard.yaml) (`dogfood-hard`) | `coupons-feature` (multi-file feature), `ledger-root-causes` (two root causes, mutation-checked regression tests), `git-regression-hunt` (find + `git revert`), `env-overrides` (regression-sensitive change); design: [docs/REAL_MODEL_BENCHMARK.md](../docs/REAL_MODEL_BENCHMARK.md#3-hard-benchmark-design--dogfood-hard-v1-offline-validated) |

Evaluation criteria (in each suite file):

- **finished** (`completed`): the agent must end with a final answer; a run
  stopped by a step or time limit fails even if its files happen to be right.
- **Visible checks**: the tests the agent is told about (`python3 test_*.py`,
  expected CLI output), plus "tests untouched" checks where the task forbids
  editing tests.
- **Hidden checks**: edge cases and recomputed expected values the agent never
  sees (e.g. `paginate([], 1, 5)`, SQL-injection payloads, revenue recomputed
  from the CSV).
- **Process checks** for the issue solver: branch name, commit message
  references the issue, regression test added in the commit, clean work tree.
- Non-required checks (weight 0.5) score quality without failing the run
  (e.g. "explains the root cause", "no false-positive findings").

Every task is verified by the test suite
(`tests/integration/test_improvement_loop.py`): the offline reference agent
passes it and an agent that does nothing fails it.

The GitHub Issue Solver's tasks are local repositories so they are
reproducible offline; the same agent config works with the real workflow
(`agentforge github solve owner/repo N -a dogfood/agents/github-issue-solver.yaml`),
which clones, pushes a branch and opens a **draft** PR (never merges).

## Running

```bash
# OFFLINE: reference agents on all five suites + the improvement-loop demo.
uv run python scripts/dogfood.py offline

# REAL: needs the provider's key; refuses to run (and writes nothing) without it.
docker build -f docker/sandbox.Dockerfile -t agentforge-sandbox:latest .
export ANTHROPIC_API_KEY=...
uv run python scripts/dogfood.py real --provider anthropic --model claude-sonnet-5 -r 3
uv run python scripts/dogfood.py real --provider openai --model <model> --roles coding,debugging
uv run python scripts/dogfood.py real --provider local --model <model> --base-url http://localhost:11434/v1
# add --improve-cycles 1 to let the improvement loop propose, apply and re-benchmark
```

Every run is stored in the AgentForge database (`AGENTFORGE_DATA_DIR`,
`--database-url`), so `agentforge serve` + the dashboard's **Improvement** page
show the same versions, benchmarks, failure categories and cycles.

### Recorded per task run

model, provider, benchmark (suite id + version), task, success, the individual
check results, tool calls and tool errors, duration, LLM retries and
evaluation retries, token usage, estimated cost and actual cost. Values that
were not measured are `null`, never zero: the scripted provider reports no
token usage, pricing may be unknown, and **actual cost is always `null`**
because AgentForge does not read provider billing.

## The improvement-loop demo (offline)

`agents/offline/demo-coder-v1.yaml` is the coding reference agent with
`max_steps: 3`, too small for the tasks. The script benchmarks it (0/6), the
failure analysis classifies every failure as `step_limit`, the rule-based
proposer raises `limits.max_steps` to the suite's cap (20), the change is
stored as agent **v2**, v2 is benchmarked on the identical suite snapshot (6/6)
and the comparison is recorded (`results/offline/improvement-demo/`).

This demonstrates the loop's mechanics only: the scripted agent replays fixed
turns, so the "improvement" is a configuration fix, not model behaviour, and
prompt changes cannot affect it. Demonstrating that the loop improves a real
agent needs real-model runs.

## Status

See [`results/README.md`](results/README.md) for the latest recorded results.
