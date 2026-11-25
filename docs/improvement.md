# Agent improvement loop

AgentForge helps you improve an agent systematically, not just run it:

```
agent version N ─► benchmark ─► evaluation ─► failure analysis ─► improvement proposal
      ▲                                                                   │
      └── compare N vs N+1 ◄── benchmark again ◄── agent version N+1 ◄────┘
```

Every step is persisted and nothing is overwritten: agent versions, benchmark
runs (with their suite snapshots), the analysis, the proposal, the applied
changes and the comparison together form the agent's improvement history.

## Building blocks

| Step | What exists | Where |
|---|---|---|
| Agent versions | Every create/update of a stored agent writes an immutable snapshot (`agent_versions`): version, config, source (`created`, `updated`, `improvement`, `revert`), change summary, parent version, improvement cycle id. Updating with an identical config is a no-op. | `AgentRepository`, `GET /agents/{id}/versions` |
| Benchmark provenance | A benchmark run records the stored agent id and version it ran (`agent_id`, `agent_version`) and its **result class**. | `BenchmarkRun` |
| Failure analysis | Classifies every failed run from its record (status, error, evaluator results, tool calls) into a category, with evidence. | `agentforge.improvement.analysis` |
| Trace-level diagnosis | Reads each failed run's trace for signals (repeated calls, unverified changes, …) and names the stage — planning, execution, verification, reasoning, reporting — the failure points to. Rule-based. | `agentforge.improvement.diagnosis` |
| Proposal | Rule-based, deterministic config changes that cite the category, evidence runs and rationale — or your own changes, or (optional, off by default) suggestions from a model the operator configured. | `agentforge.improvement.proposal`, `agentforge.improvement.llm_proposer` |
| Comparison | Candidate vs baseline on the same suite snapshot: pass-rate delta, Wilson 95% intervals, per-task changes, category deltas, verdict. | `agentforge.improvement.comparison` |
| Cycle | One pass through the loop, with status `proposed → applied → evaluating → evaluated` (or `rejected` / `failed`). | `ImprovementCycle`, `improvement_cycles` table |

## Result classes: offline vs real

`result_class` is `offline` for the scripted provider and `real` for every
model provider. It is derived from the agent config and cannot be set by a
caller. Offline results validate the pipeline and the benchmark; they say
nothing about a model. Comparisons across classes are refused
(`verdict: not_comparable`), reports are stored under `…/offline/` or
`…/real/`, and the dashboard lists the two classes separately.

## Failure categories

| Category | Derived from | Agent problem? |
|---|---|---|
| `setup`, `internal`, `cancelled`, `missing_record` | task setup error, crash, cancellation, missing run | No — fix the benchmark/environment first |
| `timeout`, `step_limit`, `tool_budget`, `tool_errors` | the run's stop reason | Yes |
| `llm_error`, `llm_refusal` | provider error / refusal | Partly |
| `tests_failed` | a failed `command` evaluator | Yes |
| `workspace_state` | failed `file_exists` / `file_contains` | Yes |
| `wrong_output` | failed `output_contains` / `output_matches` | Yes |
| `no_final_answer` | failed `completed` | Yes |
| `process_not_followed` | failed `tool_used` | Yes |
| `inefficient` | failed `max_steps` evaluator | Yes |
| `judge_rejected` | failed `llm_judge` | Yes |
| `evaluation_failed` | a failed custom evaluator | Inspect |

When several required evaluators fail, the primary category is the most
fundamental (e.g. `tests_failed` before `inefficient`); the others are listed
as secondary. Tool issues (invalid inputs, denials, errors) are counted across
all runs.

## Trace-level diagnosis

A category says *what* stopped a run or which check failed. The diagnosis
(`agentforge.improvement.diagnosis`) reads the run's recorded trace — the
ordered tool calls, the plan and the evaluator results — and says *where in
its work* the run went wrong. It is rule-based and deterministic; no model
reads the trace.

Each tool call is first given a phase from the tool's declared permissions:
`explore` (read-only), `modify` (writes files, git or GitHub state), `execute`
(runs a process) or `other` (network, memory, unknown tools). From the phases
the diagnosis derives **signals**, which are plain observations:

| Signal | Observed in the trace |
|---|---|
| `no_tool_calls` | the agent made no tool calls |
| `read_only` | no call changed a file and no command was run |
| `plan_missing` | `planner.strategy` is `plan_execute` but no plan was recorded |
| `repeated_call` | an identical call (same tool, same arguments) three or more times with no change in between |
| `trailing_tool_errors` | the last two or more tool calls all failed |
| `unverified_change` | the run ended right after its last change, without reading or running anything |
| `last_command_failed` | the last command the agent ran exited non-zero, timed out or errored |

and a **stage**, the first of these rules that matches:

| Stage | Rule |
|---|---|
| `reporting` | the workspace checks (`command`, `file_exists`, `file_contains`) passed and only final-answer checks failed |
| `planning` | the task has workspace checks, and the run shows `no_tool_calls` or `read_only` — it never attempted a change (also when a limit stopped it while still exploring) |
| `execution` | a limit stopped the run after it had started acting, or it shows `repeated_call` or `trailing_tool_errors` |
| `verification` | the task has workspace checks and the run shows `unverified_change` or `last_command_failed` |
| `reasoning` | none of the above, and a workspace or final-answer check failed: the trace shows no process defect, so the defect is in what the agent wrote or concluded |
| `undetermined` | none of the above (e.g. only a `tool_used` or `llm_judge` check failed) |

Runs that failed for reasons a trace cannot explain — setup, cancellation,
internal errors, provider errors and refusals — are not diagnosed.

The analysis reports the diagnosis per failed run (`failures[].diagnosis`:
stage, signals, a line per signal with what was observed, calls per phase)
and totals (`stages`, `signals`). `agentforge improve analyze` prints them,
the dashboard shows them with each failed run, and
`GET /improvements/diagnosis` returns the vocabulary. The rule-based proposer
uses the diagnosis for notes only: it warns when a run that hit a limit was
repeating an identical call (a higher limit alone is unlikely to help) and
when failed runs never attempted a change. It does not change what is
proposed.

Read the stage as *where to look first*, not as a proven cause:

- `reasoning` is a residual, not a detection. It means the rules found no
  process defect.
- A `run_command` call may read, write or test; the diagnosis cannot tell
  which. A run that changed files only through shell commands is therefore
  never `read_only`, and re-running a different command resets
  `repeated_call`.
- Tools that are not registered in the analysing process (plugins that are
  not installed there) count as `other`.
- Analyses stored with improvement cycles before this existed have no
  diagnosis; they are not recomputed.

## Proposals

The built-in proposer (`proposer: rules`) maps categories to changes:

| Category | Proposed change |
|---|---|
| `step_limit` | raise `limits.max_steps` to the suite's cap for the failing tasks; if the agent is already at the cap, add an efficiency instruction to the prompt (limits cannot exceed the benchmark's caps) |
| `timeout` | raise `limits.timeout_seconds` up to the suite's cap, else a prompt instruction |
| `tool_budget` | raise `limits.max_tool_calls` |
| `llm_error` | raise `retry.llm_max_attempts` (only helps transient errors; see evidence) |
| `tests_failed`, `workspace_state`, `wrong_output`, `no_final_answer`, `process_not_followed`, `judge_rejected`, `inefficient`, `tool_errors` | append a targeted instruction to `system_prompt` (never twice) |
| environment categories, `llm_refusal`, custom evaluators | notes only — no config change |

Proposals never feed hidden evaluator details into the prompt, never enable
evaluation retries (which would show the agent the checks) and never change
the provider. For offline agents the proposal notes that prompt changes cannot
affect a scripted agent.

You can write the proposal yourself (`proposer: manual`): a list of
`{path, value, operation?, rationale?}`. Only these paths may change:
`system_prompt`, `tools`, `model.model`, `model.temperature`,
`model.max_tokens`, `limits.*` (steps, timeout, tool calls, consecutive tool
errors), `retry.llm_max_attempts`, `retry.evaluation_retries`, `planner.*`,
`memory.enabled`, `memory.recall_limit`, `memory.keep_recent_messages`,
`memory.search`, `memory.min_similarity`.
Credentials, endpoints (`model.base_url`, `api_key_env`), the sandbox and tool
settings cannot be changed through the loop; the resulting config also passes
the server policy.

## Model-assisted proposals (optional)

`proposer: llm` asks a model for the changes instead of the rules. It is off
until the operator names the model in a server setting, a JSON
[`ModelConfig`](../src/agentforge/core/config.py):

```bash
AGENTFORGE_IMPROVEMENT_PROPOSER_MODEL='{"provider": "anthropic", "model": "<model id>", "max_tokens": 2000}'
agentforge improve propose BENCH_ID --proposer llm    # one model call; records a cycle like any other
agentforge improve run BENCH_ID --proposer llm        # applies each proposal without review
```

Through the API: `POST /improvements` with `"proposer": "llm"`. The request
cannot name a model, an endpoint or a key; the setting is the only source, so
a caller cannot choose where the analysis and the server's credential go.
The rule-based proposer stays the default everywhere.

**What the model is shown:** the agent's values at the paths it may change
(the system prompt among them) and its tool list; the failure categories and
the diagnosis stages and signals with their counts and meanings; per failed
run the task id, category, stage and signals; the tool-issue counts; the
suite's step and time caps. Secrets known to the process are redacted first.

**What it is never shown:** anything a run or an evaluator wrote — evaluator
details, error messages, tool arguments and outputs, final answers — and the
task goals. Two reasons: a hidden check's output must not end up in a prompt
the model writes (the next benchmark would then measure the leak), and text
produced by a run could carry instructions for the proposer.

**What it may change** is narrower than the manual allowlist:

| Not available to the model | Why |
|---|---|
| `tools` | widens what the agent may do |
| `model.model` | changes what is measured and what a run costs |
| `retry.evaluation_retries` | shows the agent the checks |

`system_prompt` can only be appended to (at most 1 200 characters per
change); at most 8 changes per proposal.

The answer is treated as untrusted input. Each suggestion is checked on its
own; one that fails a check is dropped and listed in the proposal's notes
(`dropped a suggested change (…): reason`), and the rest are kept:
unknown or forbidden paths, a `set` on the system prompt, values of the wrong
type (`true` for a number is refused, not read as 1), values the config
schema rejects, repeated paths, values equal to the current one.
`limits.max_steps` and `limits.timeout_seconds` above the suite's cap for the
failed tasks are lowered to the cap. Categories the analysis did not find are
removed from `addresses`, and the evidence run ids are taken from the
analysis, never from the model. Rationales and notes are clipped and
redacted. What is applied later still passes `apply`'s checks and the server
policy, as for every proposal.

The proposal records the call in `proposer_call`: provider, model, token
usage and cost (`null` when the model's pricing is unknown; never
estimated). If the call fails, times out (120 s) or the answer contains no
JSON object, the command fails and no cycle is recorded; there is no retry
and no silent fallback to the rules. When no run failed, the model is not
called.

Limits, stated plainly:

- **It has only been run against the scripted provider** (tests). No real
  model has produced a proposal with it, so whether its proposals are better
  than the rules' is unknown; finding out needs credentials and a budget
  (T-009c). The prompt has not been tuned on any model.
- Because the model sees no evidence text, it reasons from categories,
  diagnosis signals and the configuration only. That is a deliberate trade
  for benchmark integrity, and it limits how specific its advice can be.
- A proposal can still be wrong, vague or unhelpful within the allowlist:
  read it before `apply`. `improve run --proposer llm` skips that reading.
- The dashboard shows such a proposal (as `Proposal (llm)`) and can apply,
  evaluate and reject it, but its *Propose improvement* button always uses
  the rules, and it does not show the call's tokens.

## Comparison and verdicts

The candidate benchmark reuses the baseline's exact suite snapshot, tasks and
repeat count. Two runs are comparable only with the same suite id and
version, identical task definitions and the same result class.

| Verdict | Meaning |
|---|---|
| `improved` / `regressed` | pass rate changed and the 95% Wilson intervals do not overlap |
| `inconclusive` | a difference the sample cannot establish — run more repeats |
| `unchanged` | every task has the same pass rate |
| `not_comparable` | different suite/version/task definitions or result classes |

Per task: `fixed` (never → always passed), `broken`, `better`, `worse`,
`unchanged`. Offline comparisons carry a note that deterministic replays make
the intervals meaningless as evidence about models.

## Using it

CLI:

```bash
agentforge bench run SUITE.yaml -a AGENT.yaml --save-agent -r 3   # stores AGENT as vN, links the benchmark
agentforge improve analyze BENCH_ID                              # failure categories, stages + evidence
agentforge improve propose BENCH_ID [--changes my-changes.yaml]  # records a cycle
agentforge improve propose BENCH_ID --proposer llm               # ask the configured model (see above)
agentforge improve apply CYCLE_ID [--change c1]                  # creates vN+1
agentforge improve evaluate CYCLE_ID                             # benchmarks vN+1 and compares
agentforge improve reject CYCLE_ID --reason "..."                # decline / revert (stored as a new version)
agentforge improve run BENCH_ID --cycles 3                       # the whole loop; stops when nothing to propose,
                                                                 # when all tasks pass, or reverts a regression
agentforge improve history AGENT_NAME                            # versions, benchmarks, cycles
agentforge bench compare BASELINE_ID CANDIDATE_ID
agentforge bench gate --baseline BASELINE --candidate CANDIDATE    # CI decision: exit 0/1/2 (regression-gate.md)
agentforge bench report BENCH_ID [--out DIR]                     # JSON + Markdown under DIR/<offline|real>/
```

API: see [api.md](api.md#improvement-loop). Dashboard: **Improvement** lists
agents with their latest offline and real results, the improvement history
across agents and the experiment history; an agent's page shows its versions
(with config diffs), benchmark runs by result class, the failure analysis of a
selected run, and each cycle's proposal, comparison and actions (apply,
evaluate, reject/revert).

## Deleting an agent

Deleting a stored agent deletes its versions and improvement cycles; its
runs and benchmark runs are kept (their `agent_id` is cleared). Keep agents
whose history matters.

## Limitations

- Both proposers only change configuration and prompt guidance; neither
  rewrites tools or code. The model-assisted proposer is optional and has not
  been run with a real model (see its section above).
- Categories are derived from evaluator types, so custom evaluators map to
  `evaluation_failed` unless they are named after a built-in type.
- The trace-level diagnosis is a set of heuristics over the recorded tool
  calls (see its section above); it does not read the model's text.
- With few tasks and repeats most real comparisons will be `inconclusive`;
  that is the honest answer, not a defect.
