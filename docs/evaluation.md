# Evaluation

## Concepts

- An **evaluator** checks one aspect of a run and returns `passed` and a
  `score` in [0, 1] (defaults to 1/0 when the evaluator gives no score).
- An **evaluation** aggregates evaluator results: `score` is the
  weight-averaged score; `passed` is true when every evaluator marked
  `required` (the default) passed.
- **Execution status vs. task success**: `run.status == succeeded` means the
  agent produced a final answer; `run.evaluation.passed` means the task was
  actually accomplished.

Evaluators are specified declaratively; extra keys are parameters:

```yaml
evaluators:
  - type: command
    name: tests
    command: python3 -m pytest -q
    timeout_seconds: 300
  - type: file_contains
    path: CHANGELOG.md
    pattern: '^## \[Unreleased\]'
    flags: m
    required: false
    weight: 0.5
```

## Built-in evaluators

| Type | Parameters | Passes when |
|---|---|---|
| `completed` | — | the run ended with a final answer (not failed/timed out/cancelled) |
| `output_contains` | `text` (str or list), `case_sensitive`, `mode` (`all`/`any`) | final answer contains the text(s); score = fraction found in `all` mode |
| `output_matches` | `pattern`, `flags` (`i`,`m`,`s`) | final answer matches the regex |
| `file_exists` | `path` | the workspace file exists |
| `file_contains` | `path`, `text` or `pattern`, `flags`, `case_sensitive` | the file contains the text / matches |
| `command` | `command`, `expect_exit_code` (0), `timeout_seconds`, `cwd` | the command exits as expected **in the run's sandbox** |
| `max_steps` | `max_steps` | the run used at most N action steps; score degrades proportionally |
| `tool_used` | `tool`, `min_calls`, `successful_only` | the tool was called enough times |
| `llm_judge` | `rubric`, `model` (a ModelConfig), `pass_threshold`, `include_tool_calls` | the judge's score ≥ threshold |
| `python` | `class: module:ClassName` + its params | your evaluator decides |

Evaluator exceptions are recorded as failed results with the error message;
invalid parameters are configuration errors.

### LLM judge caveats

Judge scores are noisy and can be biased towards verbose or confident
answers. Prefer deterministic checks; use a judge as a secondary signal, with
a different model from the one being evaluated where possible.

## Evaluation-driven retries

With `retry.evaluation_retries: N`, a failed evaluation is fed back to the
agent ("Your work was checked and did not pass yet: ...") and the loop
continues, up to N times. Each evaluation is recorded as a step.

## Custom evaluators

```python
from agentforge.evaluation import EvaluationContext, Evaluator, Verdict, register_evaluator
from agentforge.evaluation.base import NoParams


class MaxFilesParams(NoParams):
    max_files: int


@register_evaluator
class MaxFilesChanged(Evaluator):
    type_name = "max_files_changed"
    description = "At most N files were written."
    Params = MaxFilesParams

    async def check(self, ctx: EvaluationContext) -> Verdict:
        written = {c.arguments.get("path") for c in ctx.run.tool_calls if c.tool == "write_file"}
        ok = len(written) <= self.params.max_files
        return Verdict(passed=ok, details=f"{len(written)} files written")
```

Register via import, the `agentforge.evaluators` entry-point group, or
reference directly with `{type: python, class: "my_pkg.evals:MaxFilesChanged", max_files: 3}`.

## Metrics

`RunMetrics` is computed from the run record only:

| Metric | Source |
|---|---|
| `duration_seconds` | `finished_at - started_at` |
| `steps`, `llm_calls`, `llm_retries` | action steps; LLM call records and their attempt counts |
| `evaluation_retries` | number of evaluation steps − 1 |
| `tool_calls`, `tool_errors`, `tool_success_rate` | tool call records (any non-success status is an error) |
| `errors` | step errors + run error |
| `input_tokens`, `output_tokens` | provider-reported usage |
| `cost_usd` | sum of per-call estimates — `None` unless **every** call had known pricing |

Prices come from the built-in table (Anthropic list prices; zero for
`scripted`/`local`) plus an optional `AGENTFORGE_PRICING_FILE`. Costs are
estimates; verify against your provider bill.
