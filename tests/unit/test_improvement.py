"""Failure analysis, proposals, comparison and reports (pure functions, no storage)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agentforge.benchmarks.report import build_report, render_markdown, report_path, save_report
from agentforge.benchmarks.runner import BenchmarkRun, ResultClass, TaskRunResult, summarize
from agentforge.benchmarks.spec import BenchmarkSuite
from agentforge.core.config import AgentConfig, ModelConfig
from agentforge.core.errors import ImprovementError
from agentforge.core.ids import utcnow
from agentforge.core.models import (
    ErrorInfo,
    EvaluationResult,
    EvaluatorResult,
    LLMCallRecord,
    Run,
    RunMetrics,
    RunStatus,
    Step,
    StepKind,
    TokenUsage,
    ToolCallRecord,
    ToolCallStatus,
)
from agentforge.improvement import (
    ChangeOperation,
    FailureCategory,
    ProposedChange,
    Verdict,
    analyze,
    apply_changes,
    classify_run,
    compare_benchmarks,
    prepare_manual,
    propose,
)

SCRIPTED = ModelConfig(provider="scripted", model="s")
REAL = ModelConfig(provider="anthropic", model="claude-sonnet-5")


def config(model: ModelConfig = SCRIPTED, **overrides: Any) -> AgentConfig:
    return AgentConfig.model_validate({"name": "a", "model": model, **overrides})


def suite(version: str = "1", goal_suffix: str = "") -> BenchmarkSuite:
    return BenchmarkSuite.model_validate(
        {
            "id": "s",
            "name": "S",
            "version": version,
            "defaults": {"max_steps": 20, "timeout_seconds": 300},
            "tasks": [
                {"id": "t1", "goal": "one" + goal_suffix, "evaluators": [{"type": "completed"}]},
                {"id": "t2", "goal": "two", "evaluators": [{"type": "completed"}]},
            ],
        }
    )


def evaluation(*results: tuple[str, bool]) -> EvaluationResult:
    items = [
        EvaluatorResult(name=n, passed=p, score=float(p), details=f"{n} details")
        for n, p in results
    ]
    return EvaluationResult(passed=all(p for _, p in results), score=0.0, results=items)


def run(
    task: str = "t1",
    *,
    status: RunStatus = RunStatus.SUCCEEDED,
    error: ErrorInfo | None = None,
    evaluation_result: EvaluationResult | None = None,
    evaluators: list[dict[str, Any]] | None = None,
    tool_calls: list[ToolCallRecord] | None = None,
    usage: TokenUsage | None = None,
    model: ModelConfig = SCRIPTED,
) -> Run:
    now = utcnow()
    step = Step(index=0, kind=StepKind.ACTION, tool_calls=tool_calls or [])
    if usage is not None:
        step.llm_call = LLMCallRecord(
            provider=model.provider,
            model=model.model,
            started_at=now,
            finished_at=now,
            latency_ms=1,
            usage=usage,
            cost_usd=0.01,
        )
    return Run(
        agent_name="a",
        config=config(model),
        goal="g",
        status=status,
        error=error,
        evaluation=evaluation_result,
        evaluators=evaluators or [],
        steps=[step],
        labels={"task": task, "repeat": "1"},
        metrics=RunMetrics(
            steps=3,
            tool_calls=len(tool_calls or []),
            duration_seconds=1.5,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            cost_usd=0.01 if usage else None,
        ),
        usage=usage or TokenUsage(),
    )


def tool_call(
    status: ToolCallStatus, error: str = "boom", tool: str = "read_file"
) -> ToolCallRecord:
    now = utcnow()
    return ToolCallRecord(
        id="c",
        tool=tool,
        status=status,
        error=error,
        started_at=now,
        finished_at=now,
        duration_ms=1,
    )


def bench(
    runs: list[Run],
    *,
    model: ModelConfig = SCRIPTED,
    suite_version: str = "1",
    the_suite: BenchmarkSuite | None = None,
    **agent: Any,
) -> BenchmarkRun:
    results = [
        TaskRunResult(
            task_id=r.labels["task"],
            repeat=int(r.labels["repeat"]),
            run_id=r.id,
            status=r.status,
            passed=bool(r.evaluation and r.evaluation.passed),
            score=r.evaluation.score if r.evaluation else 0.0,
            steps=r.metrics.steps,
        )
        for r in runs
    ]
    s = the_suite or suite(suite_version)
    return BenchmarkRun(
        suite_id=s.id,
        suite_name=s.name,
        agent_name="a",
        agent_config=config(model, **agent),
        suite=s,
        status=RunStatus.SUCCEEDED,
        results=results,
        summary=summarize(results, [t.id for t in s.tasks]),
        agent_id="agt_x",
        agent_version=1,
    )


# ------------------------------------------------------------------ classify
@pytest.mark.parametrize(
    ("status", "error_type", "expected"),
    [
        (RunStatus.FAILED, "setup", FailureCategory.SETUP),
        (RunStatus.CANCELLED, "cancelled", FailureCategory.CANCELLED),
        (RunStatus.TIMED_OUT, "timeout", FailureCategory.TIMEOUT),
        (RunStatus.FAILED, "max_steps", FailureCategory.STEP_LIMIT),
        (RunStatus.FAILED, "tool_errors", FailureCategory.TOOL_ERRORS),
        (RunStatus.FAILED, "llm.refusal", FailureCategory.LLM_REFUSAL),
        (RunStatus.FAILED, "llm.rate_limit", FailureCategory.LLM_ERROR),
        (RunStatus.FAILED, "internal", FailureCategory.INTERNAL),
    ],
)
def test_classify_run_errors(status: RunStatus, error_type: str, expected: FailureCategory) -> None:
    failure = classify_run(run(status=status, error=ErrorInfo(type=error_type, message="m")))
    assert failure is not None
    assert failure.category == expected
    assert any(error_type in e for e in failure.evidence)


@pytest.mark.parametrize(
    ("evaluator", "expected"),
    [
        ({"type": "command", "name": "tests"}, FailureCategory.TESTS_FAILED),
        ({"type": "file_contains", "path": "x", "text": "y"}, FailureCategory.WORKSPACE_STATE),
        ({"type": "output_contains", "text": "y"}, FailureCategory.WRONG_OUTPUT),
        ({"type": "tool_used", "tool": "git_commit"}, FailureCategory.PROCESS_NOT_FOLLOWED),
        ({"type": "max_steps", "max_steps": 2}, FailureCategory.INEFFICIENT),
        ({"type": "python", "class": "m:C"}, FailureCategory.EVALUATION_FAILED),
    ],
)
def test_classify_run_evaluator_failures(
    evaluator: dict[str, Any], expected: FailureCategory
) -> None:
    name = evaluator.get("name") or evaluator["type"]
    failed = run(evaluation_result=evaluation((name, False)), evaluators=[evaluator])
    failure = classify_run(failed)
    assert failure is not None and failure.category == expected
    assert any(f"{name} details" in e for e in failure.evidence)


def test_classify_prefers_fundamental_evaluation_failure() -> None:
    specs = [{"type": "max_steps", "max_steps": 2}, {"type": "command", "name": "tests"}]
    failed = run(
        evaluation_result=evaluation(("max_steps", False), ("tests", False)), evaluators=specs
    )
    failure = classify_run(failed)
    assert failure is not None
    assert failure.category == FailureCategory.TESTS_FAILED
    assert failure.secondary == [FailureCategory.INEFFICIENT]


def test_classify_passed_run_and_budget_exhaustion() -> None:
    assert classify_run(run(evaluation_result=evaluation(("ok", True)))) is None
    exhausted = run(
        status=RunStatus.FAILED,
        error=ErrorInfo(type="max_steps", message="limit"),
        tool_calls=[tool_call(ToolCallStatus.DENIED, "tool call budget exhausted; finish")],
    )
    failure = classify_run(exhausted)
    assert failure is not None
    assert failure.category == FailureCategory.TOOL_BUDGET
    assert FailureCategory.STEP_LIMIT in failure.secondary


def test_analyze_counts_categories_tool_issues_and_missing_runs() -> None:
    ok = run("t1", evaluation_result=evaluation(("ok", True)))
    limit = run(
        "t2",
        status=RunStatus.FAILED,
        error=ErrorInfo(type="max_steps", message="limit"),
        tool_calls=[tool_call(ToolCallStatus.INVALID_INPUT)],
    )
    b = bench([ok, limit])
    b.results.append(
        TaskRunResult(
            task_id="t2",
            repeat=2,
            run_id="run_gone",
            status=RunStatus.FAILED,
            passed=False,
            score=0.0,
        )
    )
    analysis = analyze(b, {ok.id: ok, limit.id: limit})
    assert (analysis.runs, analysis.passed, analysis.failed) == (3, 1, 2)
    assert analysis.categories == {"step_limit": 1, "missing_record": 1}
    assert analysis.tool_issues == {"read_file": {"invalid_input": 1}}
    assert analysis.result_class == ResultClass.OFFLINE
    by_task = {t.task_id: t for t in analysis.tasks}
    assert by_task["t1"].passed == 1 and by_task["t2"].runs == 2


# ------------------------------------------------------------------ propose
def _analysis(runs: list[Run], **agent: Any) -> Any:
    b = bench(runs, **agent)
    return analyze(b, {r.id: r for r in runs}), b


def test_propose_raises_step_limit_up_to_suite_cap() -> None:
    limited = run(status=RunStatus.FAILED, error=ErrorInfo(type="max_steps", message="x"))
    analysis, b = _analysis([limited], limits={"max_steps": 3})
    proposal = propose(analysis, b.agent_config, b.suite)
    [change] = proposal.changes
    assert (change.id, change.path, change.current, change.value) == (
        "c1",
        "limits.max_steps",
        3,
        20,
    )
    assert change.evidence == [limited.id]
    assert FailureCategory.STEP_LIMIT in change.addresses
    assert apply_changes(b.agent_config, proposal.changes).limits.max_steps == 20


def test_propose_uses_prompt_when_limit_already_at_cap_and_notes_offline() -> None:
    limited = run(status=RunStatus.FAILED, error=ErrorInfo(type="max_steps", message="x"))
    analysis, b = _analysis([limited], limits={"max_steps": 50})
    proposal = propose(analysis, b.agent_config, b.suite)
    [change] = proposal.changes
    assert change.path == "system_prompt" and change.operation == ChangeOperation.APPEND
    assert any("prompt changes cannot affect" in n for n in proposal.notes)
    updated = apply_changes(b.agent_config, proposal.changes)
    assert updated.system_prompt.endswith(str(change.value))
    # Idempotent: once the lesson is in the prompt it is not proposed again.
    again = propose(analysis, updated, b.suite)
    assert again.changes == []
    assert any("already contains" in n for n in again.notes)


def test_propose_ignores_infrastructure_failures() -> None:
    setup = run(status=RunStatus.FAILED, error=ErrorInfo(type="setup", message="x"))
    analysis, b = _analysis([setup])
    proposal = propose(analysis, b.agent_config, b.suite)
    assert proposal.changes == []
    assert proposal.notes and "outside the agent" in proposal.notes[0]


def test_propose_prompt_lessons_merge_and_retries() -> None:
    specs = [{"type": "command", "name": "tests"}]
    runs = [
        run(evaluation_result=evaluation(("tests", False)), evaluators=specs, model=REAL),
        run(status=RunStatus.FAILED, error=ErrorInfo(type="llm.server", message="503"), model=REAL),
    ]
    analysis, b = _analysis(runs, model=REAL)
    proposal = propose(analysis, b.agent_config, b.suite)
    assert sorted(c.path for c in proposal.changes) == ["retry.llm_max_attempts", "system_prompt"]
    assert not any("prompt changes cannot affect" in n for n in proposal.notes)


def test_apply_changes_enforces_allowlist_and_validation() -> None:
    base = config()
    with pytest.raises(ImprovementError, match="cannot be changed"):
        apply_changes(base, [ProposedChange(path="model.provider", value="anthropic")])
    with pytest.raises(ImprovementError, match="cannot be changed"):
        apply_changes(base, [ProposedChange(path="sandbox.kind", value="local")])
    with pytest.raises(ImprovementError, match="only supported for system_prompt"):
        apply_changes(
            base, [ProposedChange(path="tools", operation=ChangeOperation.APPEND, value="x")]
        )
    with pytest.raises(ImprovementError, match="invalid config"):
        apply_changes(base, [ProposedChange(path="limits.max_steps", value=0)])
    manual = prepare_manual(
        base, [ProposedChange(path="limits.timeout_seconds", value=120, rationale="faster")]
    )
    assert manual.proposer == "manual"
    assert (manual.changes[0].id, manual.changes[0].current) == ("c1", 600.0)
    with pytest.raises(ImprovementError, match="at least one"):
        prepare_manual(base, [])


# ------------------------------------------------------------------ compare
def _passing(task: str, passed: bool, model: ModelConfig = SCRIPTED) -> Run:
    return run(task, evaluation_result=evaluation(("ok", passed)), model=model)


def test_compare_verdicts() -> None:
    fail = [_passing(t, False) for t in ("t1", "t2") for _ in range(5)]
    ok = [_passing(t, True) for t in ("t1", "t2") for _ in range(5)]
    improved = compare_benchmarks(bench(fail), bench(ok))
    assert improved.comparable and improved.verdict == Verdict.IMPROVED
    assert improved.significant and improved.pass_rate_delta == 1.0
    assert {t.change.value for t in improved.tasks} == {"fixed"}
    assert any("deterministic replays" in n for n in improved.notes)
    assert compare_benchmarks(bench(ok), bench(fail)).verdict == Verdict.REGRESSED
    assert compare_benchmarks(bench(ok), bench(ok)).verdict == Verdict.UNCHANGED
    small = compare_benchmarks(
        bench([_passing("t1", False), _passing("t2", True)]),
        bench([_passing("t1", True), _passing("t2", True)]),
    )
    assert small.verdict == Verdict.INCONCLUSIVE and not small.significant
    assert any("overlap" in n for n in small.notes)


def test_compare_never_mixes_offline_and_real() -> None:
    offline = bench([_passing("t1", True)])
    real = bench([_passing("t1", True, REAL)], model=REAL)
    assert real.result_class == ResultClass.REAL
    result = compare_benchmarks(offline, real)
    assert not result.comparable and result.verdict == Verdict.NOT_COMPARABLE
    assert "never compared" in result.reasons[0]
    assert result.baseline is None and result.tasks == []


def test_compare_requires_same_suite_version_and_definitions() -> None:
    base = bench([_passing("t1", True)])
    other_version = bench([_passing("t1", True)], suite_version="2")
    assert "suite versions" in compare_benchmarks(base, other_version).reasons[0]
    changed = bench([_passing("t1", True)], the_suite=suite(goal_suffix=" (edited)"))
    assert "without a suite version bump" in compare_benchmarks(base, changed).reasons[0]


def test_result_class_is_derived_not_trusted() -> None:
    data = bench([_passing("t1", True)]).model_dump(mode="json")
    data["result_class"] = "real"
    assert BenchmarkRun.model_validate(data).result_class == ResultClass.OFFLINE


# ------------------------------------------------------------------ report
def test_report_never_fabricates_tokens_or_cost(tmp_path: Path) -> None:
    offline_run = _passing("t1", True)
    report = build_report(bench([offline_run]), {offline_run.id: offline_run})
    record = report.runs[0]
    assert report.result_class == ResultClass.OFFLINE
    assert record.input_tokens is None and record.output_tokens is None
    assert record.estimated_cost_usd is None and record.actual_cost_usd is None
    assert report.summary.total_input_tokens is None
    assert any("OFFLINE" in n for n in report.notes)
    assert record.checks[0].name == "ok" and record.success

    real_run = run(
        evaluation_result=evaluation(("ok", True)),
        usage=TokenUsage(input_tokens=100, output_tokens=20),
        model=REAL,
    )
    real = build_report(bench([real_run], model=REAL), {real_run.id: real_run})
    assert (real.runs[0].input_tokens, real.runs[0].output_tokens) == (100, 20)
    assert real.runs[0].estimated_cost_usd == 0.01 and real.runs[0].actual_cost_usd is None
    assert real.summary.total_input_tokens == 100

    offline_path = save_report(tmp_path, report)
    real_path = save_report(tmp_path, real)
    assert offline_path.parts[-3] == "offline" and real_path.parts[-3] == "real"
    assert offline_path == report_path(tmp_path, report)
    assert offline_path.with_suffix(".md").read_text().startswith("# S — OFFLINE / SCRIPTED")
    assert "REAL MODEL PROVIDER" in render_markdown(real)


def test_report_marks_missing_runs() -> None:
    b = bench([_passing("t1", False)])
    report = build_report(b, {})
    assert report.runs[0].status == "missing" and report.runs[0].tool_calls is None


def test_token_budget_is_its_own_category() -> None:
    failure = classify_run(
        run(status=RunStatus.FAILED, error=ErrorInfo(type="token_budget", message="x"))
    )
    assert failure is not None and failure.category == FailureCategory.TOKEN_BUDGET
