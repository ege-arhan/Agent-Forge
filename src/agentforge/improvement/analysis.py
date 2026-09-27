"""Failure analysis: classify why benchmark runs failed, from recorded data only.

Every classification is derived from the stored run record (status, error,
evaluator results and tool-call records); nothing is inferred by a model.
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum

from pydantic import BaseModel, Field

from agentforge.benchmarks.runner import BenchmarkRun, ResultClass
from agentforge.core.models import EvaluatorResult, Run, RunStatus, ToolCallStatus


class FailureCategory(StrEnum):
    # Infrastructure / benchmark problems: not the agent's fault.
    SETUP = "setup"
    INTERNAL = "internal"
    CANCELLED = "cancelled"
    MISSING_RECORD = "missing_record"
    # The run stopped before the agent finished.
    TIMEOUT = "timeout"
    STEP_LIMIT = "step_limit"
    TOOL_BUDGET = "tool_budget"
    TOKEN_BUDGET = "token_budget"  # noqa: S105 - category name, not a secret
    TOOL_ERRORS = "tool_errors"
    LLM_ERROR = "llm_error"
    LLM_REFUSAL = "llm_refusal"
    # The agent finished but its result failed evaluation.
    TESTS_FAILED = "tests_failed"
    WORKSPACE_STATE = "workspace_state"
    WRONG_OUTPUT = "wrong_output"
    NO_FINAL_ANSWER = "no_final_answer"
    INEFFICIENT = "inefficient"
    PROCESS_NOT_FOLLOWED = "process_not_followed"
    JUDGE_REJECTED = "judge_rejected"
    EVALUATION_FAILED = "evaluation_failed"
    NOT_EVALUATED = "not_evaluated"


CATEGORY_DESCRIPTIONS: dict[FailureCategory, str] = {
    FailureCategory.SETUP: "Task setup failed (benchmark or environment problem).",
    FailureCategory.INTERNAL: "AgentForge internal error.",
    FailureCategory.CANCELLED: "The run was cancelled.",
    FailureCategory.MISSING_RECORD: "The run record is missing.",
    FailureCategory.TIMEOUT: "The run exceeded its time limit.",
    FailureCategory.STEP_LIMIT: "The run reached its step limit before finishing.",
    FailureCategory.TOOL_BUDGET: "The run exhausted its tool-call budget.",
    FailureCategory.TOKEN_BUDGET: "The run was stopped by its token budget.",
    FailureCategory.TOOL_ERRORS: "The run was stopped after consecutive failing tool calls.",
    FailureCategory.LLM_ERROR: "The model provider returned an error.",
    FailureCategory.LLM_REFUSAL: "The model declined the request.",
    FailureCategory.TESTS_FAILED: "A test/command check failed.",
    FailureCategory.WORKSPACE_STATE: "Expected files or file contents were wrong.",
    FailureCategory.WRONG_OUTPUT: "The final answer did not contain the expected result.",
    FailureCategory.NO_FINAL_ANSWER: "The agent gave no final answer.",
    FailureCategory.INEFFICIENT: "The agent used more steps than allowed by the evaluation.",
    FailureCategory.PROCESS_NOT_FOLLOWED: "A required tool/process was not used.",
    FailureCategory.JUDGE_REJECTED: "The LLM judge rejected the result.",
    FailureCategory.EVALUATION_FAILED: "A custom evaluator failed.",
    FailureCategory.NOT_EVALUATED: "The run finished without an evaluation.",
}

# Categories that say nothing about the agent; improvement proposals ignore them.
NON_AGENT_CATEGORIES = frozenset(
    {
        FailureCategory.SETUP,
        FailureCategory.INTERNAL,
        FailureCategory.CANCELLED,
        FailureCategory.MISSING_RECORD,
    }
)

_EVALUATOR_CATEGORY: dict[str, FailureCategory] = {
    "command": FailureCategory.TESTS_FAILED,
    "file_exists": FailureCategory.WORKSPACE_STATE,
    "file_contains": FailureCategory.WORKSPACE_STATE,
    "output_contains": FailureCategory.WRONG_OUTPUT,
    "output_matches": FailureCategory.WRONG_OUTPUT,
    "completed": FailureCategory.NO_FINAL_ANSWER,
    "max_steps": FailureCategory.INEFFICIENT,
    "tool_used": FailureCategory.PROCESS_NOT_FOLLOWED,
    "llm_judge": FailureCategory.JUDGE_REJECTED,
}

# When several evaluators fail, the primary category is the most fundamental one.
_EVALUATION_PRIORITY = [
    FailureCategory.NO_FINAL_ANSWER,
    FailureCategory.TESTS_FAILED,
    FailureCategory.WORKSPACE_STATE,
    FailureCategory.WRONG_OUTPUT,
    FailureCategory.PROCESS_NOT_FOLLOWED,
    FailureCategory.JUDGE_REJECTED,
    FailureCategory.EVALUATION_FAILED,
    FailureCategory.INEFFICIENT,
]

_MAX_EVIDENCE_CHARS = 400


class TaskFailure(BaseModel):
    task_id: str
    repeat: int
    run_id: str
    category: FailureCategory
    secondary: list[FailureCategory] = Field(default_factory=list)
    summary: str
    evidence: list[str] = Field(default_factory=list)


class TaskAnalysis(BaseModel):
    task_id: str
    runs: int
    passed: int
    categories: dict[str, int] = Field(default_factory=dict)


class FailureAnalysis(BaseModel):
    benchmark_run_id: str
    suite_id: str
    suite_version: str
    result_class: ResultClass
    agent_name: str
    agent_id: str | None = None
    agent_version: int | None = None
    runs: int
    passed: int
    failed: int
    categories: dict[str, int] = Field(
        default_factory=dict, description="Primary failure category -> number of failed runs."
    )
    tool_issues: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="Tool -> non-success status -> count, over all runs (passed ones too).",
    )
    tasks: list[TaskAnalysis] = Field(default_factory=list)
    failures: list[TaskFailure] = Field(default_factory=list)

    def count(self, category: FailureCategory) -> int:
        return self.categories.get(category.value, 0)


def _clip(text: str, limit: int = _MAX_EVIDENCE_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _evaluator_types(run: Run) -> dict[str, str]:
    types: dict[str, str] = {}
    for spec in run.evaluators:
        kind = str(spec.get("type", ""))
        types[str(spec.get("name") or kind)] = kind
    return types


def _evaluation_category(result: EvaluatorResult, types: dict[str, str]) -> FailureCategory:
    kind = types.get(result.name, result.name)
    return _EVALUATOR_CATEGORY.get(kind, FailureCategory.EVALUATION_FAILED)


def _error_category(run: Run) -> FailureCategory | None:
    error_type = run.error.type if run.error else ""
    if error_type == "setup":
        return FailureCategory.SETUP
    if run.status == RunStatus.CANCELLED or error_type == "cancelled":
        return FailureCategory.CANCELLED
    if run.status == RunStatus.TIMED_OUT or error_type == "timeout":
        return FailureCategory.TIMEOUT
    if error_type == "max_steps":
        return FailureCategory.STEP_LIMIT
    if error_type == "token_budget":
        return FailureCategory.TOKEN_BUDGET
    if error_type == "tool_errors":
        return FailureCategory.TOOL_ERRORS
    if error_type == "llm.refusal":
        return FailureCategory.LLM_REFUSAL
    if error_type.startswith("llm."):
        return FailureCategory.LLM_ERROR
    if run.status == RunStatus.FAILED:
        return FailureCategory.INTERNAL
    return None


def _budget_exhausted(run: Run) -> bool:
    return any(
        call.status == ToolCallStatus.DENIED and "budget exhausted" in (call.error or "")
        for call in run.tool_calls
    )


def _tool_evidence(run: Run) -> list[str]:
    evidence: list[str] = []
    for call in run.tool_calls:
        if call.status != ToolCallStatus.SUCCESS and len(evidence) < 3:
            evidence.append(
                _clip(f"{call.tool} → {call.status.value}: {call.error or call.output}")
            )
    return evidence


def classify_run(run: Run) -> TaskFailure | None:
    """Classify a failed run; ``None`` if it passed."""
    task_id = run.labels.get("task", "")
    repeat = int(run.labels.get("repeat", "1") or 1)
    if run.evaluation is not None and run.evaluation.passed:
        return None

    evidence: list[str] = []
    secondary: list[FailureCategory] = []
    category = _error_category(run)
    if run.error:
        evidence.append(_clip(f"{run.error.type}: {run.error.message}"))

    failed_evals: list[tuple[FailureCategory, EvaluatorResult]] = []
    if run.evaluation is not None:
        types = _evaluator_types(run)
        for result in run.evaluation.results:
            if not result.passed and result.required:
                failed_evals.append((_evaluation_category(result, types), result))
        for cat, result in failed_evals:
            detail = result.details or "failed"
            evidence.append(_clip(f"{result.name} ({cat.value}): {detail}"))

    if category is None:
        if failed_evals:
            ordered = sorted(failed_evals, key=lambda item: _EVALUATION_PRIORITY.index(item[0]))
            category = ordered[0][0]
        else:
            category = FailureCategory.NOT_EVALUATED
    if _budget_exhausted(run) and category != FailureCategory.TOOL_BUDGET:
        if category in (FailureCategory.STEP_LIMIT, FailureCategory.NOT_EVALUATED):
            secondary.append(category)
            category = FailureCategory.TOOL_BUDGET
        else:
            secondary.append(FailureCategory.TOOL_BUDGET)
    for cat, _ in failed_evals:
        if cat != category and cat not in secondary:
            secondary.append(cat)
    evidence.extend(_tool_evidence(run))

    summary = CATEGORY_DESCRIPTIONS[category]
    if category == FailureCategory.STEP_LIMIT:
        summary += f" ({run.metrics.steps} steps used)"
    return TaskFailure(
        task_id=task_id,
        repeat=repeat,
        run_id=run.id,
        category=category,
        secondary=secondary,
        summary=summary,
        evidence=evidence,
    )


def analyze(bench: BenchmarkRun, runs: dict[str, Run]) -> FailureAnalysis:
    """Analyse a benchmark run given its underlying run records (keyed by run id)."""
    failures: list[TaskFailure] = []
    tool_issues: dict[str, Counter[str]] = {}
    per_task: dict[str, TaskAnalysis] = {}
    for result in bench.results:
        task = per_task.setdefault(
            result.task_id, TaskAnalysis(task_id=result.task_id, runs=0, passed=0)
        )
        task.runs += 1
        run = runs.get(result.run_id)
        if run is None:
            failure: TaskFailure | None = (
                None
                if result.passed
                else TaskFailure(
                    task_id=result.task_id,
                    repeat=result.repeat,
                    run_id=result.run_id,
                    category=FailureCategory.MISSING_RECORD,
                    summary=CATEGORY_DESCRIPTIONS[FailureCategory.MISSING_RECORD],
                    evidence=[result.error] if result.error else [],
                )
            )
        else:
            for call in run.tool_calls:
                if call.status != ToolCallStatus.SUCCESS:
                    tool_issues.setdefault(call.tool, Counter())[call.status.value] += 1
            failure = None if result.passed else classify_run(run)
            if failure is not None:
                failure.task_id = result.task_id
                failure.repeat = result.repeat
        if failure is None:
            task.passed += 1
            continue
        failures.append(failure)
        task.categories[failure.category.value] = task.categories.get(failure.category.value, 0) + 1

    categories = Counter(f.category.value for f in failures)
    return FailureAnalysis(
        benchmark_run_id=bench.id,
        suite_id=bench.suite_id,
        suite_version=bench.suite.version,
        result_class=bench.result_class,
        agent_name=bench.agent_name,
        agent_id=bench.agent_id,
        agent_version=bench.agent_version,
        runs=len(bench.results),
        passed=len(bench.results) - len(failures),
        failed=len(failures),
        categories=dict(categories.most_common()),
        tool_issues={tool: dict(c) for tool, c in sorted(tool_issues.items())},
        tasks=list(per_task.values()),
        failures=failures,
    )
