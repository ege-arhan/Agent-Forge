"""Trace-level diagnosis of failed runs (pure functions over run records)."""

from __future__ import annotations

from typing import Any

import pytest

from agentforge.benchmarks.spec import BenchmarkSuite
from agentforge.core.config import AgentConfig
from agentforge.core.ids import utcnow
from agentforge.core.models import (
    ErrorInfo,
    EvaluationResult,
    EvaluatorResult,
    Run,
    RunStatus,
    Step,
    StepKind,
    ToolCallRecord,
    ToolCallStatus,
)
from agentforge.improvement import (
    SIGNAL_DESCRIPTIONS,
    STAGE_DESCRIPTIONS,
    FailureCategory,
    FailureStage,
    ToolPhase,
    TraceSignal,
    analyze,
    classify_run,
    diagnose_run,
    propose,
)
from agentforge.improvement.analysis import FailureAnalysis
from agentforge.improvement.diagnosis import phase_of, registry_phases
from agentforge.tools.base import Permission

OK = ToolCallStatus.SUCCESS
TESTS = [{"type": "command", "name": "tests"}, {"type": "output_contains", "name": "answer"}]


def call(
    tool: str, status: ToolCallStatus = OK, output: str = "", **arguments: Any
) -> ToolCallRecord:
    now = utcnow()
    return ToolCallRecord(
        id="c",
        tool=tool,
        arguments=arguments,
        status=status,
        output=output,
        error=None if status == OK else "boom",
        started_at=now,
        finished_at=now,
        duration_ms=1,
    )


def failed_run(
    calls: list[ToolCallRecord],
    *,
    results: dict[str, bool] | None = None,
    evaluators: list[dict[str, Any]] | None = None,
    error: str | None = None,
    status: RunStatus | None = None,
    **config: Any,
) -> Run:
    results = {"tests": False, "answer": True} if results is None else results
    evaluation = EvaluationResult(
        passed=all(results.values()),
        score=0.0,
        results=[EvaluatorResult(name=n, passed=p, score=float(p)) for n, p in results.items()],
    )
    return Run(
        agent_name="a",
        config=AgentConfig.model_validate(
            {"name": "a", "model": {"provider": "scripted", "model": "s"}, **config}
        ),
        goal="g",
        status=status or (RunStatus.FAILED if error else RunStatus.SUCCEEDED),
        steps=[Step(index=i, kind=StepKind.ACTION, tool_calls=[c]) for i, c in enumerate(calls)],
        error=ErrorInfo(type=error, message=error) if error else None,
        evaluation=None if error else evaluation,
        evaluators=TESTS if evaluators is None else evaluators,
        labels={"task": "t1", "repeat": "1"},
    )


def stage_and_signals(run: Run) -> tuple[FailureStage, set[TraceSignal]]:
    diagnosis = diagnose_run(run)
    assert diagnosis is not None
    return diagnosis.stage, set(diagnosis.signals)


# -------------------------------------------------------------------- phases
def test_tool_phases_come_from_permissions() -> None:
    phases = registry_phases()
    assert phases["read_file"] == ToolPhase.EXPLORE
    assert phases["git_diff"] == ToolPhase.EXPLORE
    assert phases["write_file"] == ToolPhase.MODIFY
    assert phases["edit_file"] == ToolPhase.MODIFY  # reads and writes
    assert phases["git_commit"] == ToolPhase.MODIFY
    assert phases["run_command"] == ToolPhase.EXECUTE
    assert phases["http_request"] == ToolPhase.OTHER
    assert phases["remember"] == ToolPhase.OTHER
    assert phase_of(frozenset()) == ToolPhase.OTHER
    assert phase_of(frozenset({Permission.PROCESS_EXEC, Permission.FS_WRITE})) == ToolPhase.EXECUTE


# -------------------------------------------------------------------- stages
def test_planning_when_a_change_was_required_and_none_was_attempted() -> None:
    stage, signals = stage_and_signals(failed_run([]))
    assert (stage, signals) == (FailureStage.PLANNING, {TraceSignal.NO_TOOL_CALLS})

    reads = [call("read_file", path="a.py"), call("list_directory", path=".")]
    stage, signals = stage_and_signals(failed_run(reads))
    assert (stage, signals) == (FailureStage.PLANNING, {TraceSignal.READ_ONLY})

    # A write that was rejected is not an attempt that changed anything.
    denied = [call("read_file", path="a.py"), call("write_file", ToolCallStatus.DENIED, path="x")]
    assert stage_and_signals(failed_run(denied))[0] == FailureStage.PLANNING


def test_planning_notes_a_limit_hit_while_still_exploring() -> None:
    reads = [call("read_file", path=f"{i}.py") for i in range(4)]
    diagnosis = diagnose_run(failed_run(reads, error="max_steps"))
    assert diagnosis is not None
    assert diagnosis.stage == FailureStage.PLANNING
    assert "while still exploring" in diagnosis.summary
    assert diagnosis.phases == {"explore": 4}


def test_reading_only_is_not_a_planning_failure_for_an_answer_only_task() -> None:
    answer_only = [{"type": "output_contains", "name": "answer"}]
    run = failed_run(
        [call("read_file", path="data.csv")], results={"answer": False}, evaluators=answer_only
    )
    stage, signals = stage_and_signals(run)
    assert stage == FailureStage.REASONING
    assert signals == {TraceSignal.READ_ONLY}


def test_execution_when_stopped_by_a_limit_after_acting() -> None:
    calls = [call("read_file", path="a.py"), call("write_file", path="a.py")]
    assert stage_and_signals(failed_run(calls, error="max_steps"))[0] == FailureStage.EXECUTION
    assert (
        stage_and_signals(failed_run(calls, error="timeout", status=RunStatus.TIMED_OUT))[0]
        == FailureStage.EXECUTION
    )


def test_repeated_identical_call_is_an_execution_failure() -> None:
    loop = [call("write_file", path="a.py")] + [call("run_command", command="pytest")] * 3
    stage, signals = stage_and_signals(failed_run(loop))
    assert stage == FailureStage.EXECUTION
    assert TraceSignal.REPEATED_CALL in signals
    details = diagnose_run(failed_run(loop))
    assert details is not None
    assert any("run_command x3" in line for line in details.details)


def test_rerunning_a_check_after_each_change_is_not_a_repeat() -> None:
    calls: list[ToolCallRecord] = []
    for i in range(4):
        calls += [
            call("edit_file", path="a.py", old=str(i), new=str(i + 1)),
            call("run_command", output="exit_code: 0", command="pytest"),
        ]
    # ...nor is alternating two different commands (either may change state).
    calls += [call("run_command", output="exit_code: 0", command=c) for c in ["make", "pytest"] * 3]
    stage, signals = stage_and_signals(failed_run(calls))
    assert TraceSignal.REPEATED_CALL not in signals
    assert stage == FailureStage.REASONING  # verified by its own passing check, still wrong


def test_trailing_tool_errors_are_an_execution_failure() -> None:
    calls = [
        call("write_file", path="a.py"),
        call("edit_file", ToolCallStatus.ERROR, path="a.py", old="x", new="y"),
        call("edit_file", ToolCallStatus.INVALID_INPUT, path="a.py"),
    ]
    stage, signals = stage_and_signals(failed_run(calls))
    assert stage == FailureStage.EXECUTION
    assert TraceSignal.TRAILING_TOOL_ERRORS in signals
    # One failing call at the end is not a pattern.
    assert TraceSignal.TRAILING_TOOL_ERRORS not in stage_and_signals(failed_run(calls[:2]))[1]


def test_verification_when_the_run_ends_right_after_a_change() -> None:
    calls = [call("read_file", path="a.py"), call("write_file", path="a.py")]
    stage, signals = stage_and_signals(failed_run(calls))
    assert (stage, signals) == (FailureStage.VERIFICATION, {TraceSignal.UNVERIFIED_CHANGE})


@pytest.mark.parametrize(
    "last",
    [
        call("run_command", output="exit_code: 1\nstdout:\n1 failed", command="pytest"),
        call("run_command", ToolCallStatus.TIMEOUT, command="pytest"),
    ],
)
def test_verification_when_the_last_command_failed(last: ToolCallRecord) -> None:
    stage, signals = stage_and_signals(failed_run([call("write_file", path="a.py"), last]))
    assert (stage, signals) == (FailureStage.VERIFICATION, {TraceSignal.LAST_COMMAND_FAILED})


def test_reporting_when_the_workspace_checks_passed() -> None:
    calls = [call("write_file", path="a.py"), call("run_command", output="exit_code: 0")]
    run = failed_run(calls, results={"tests": True, "answer": False})
    assert stage_and_signals(run) == (FailureStage.REPORTING, set())


def test_undetermined_when_only_a_process_check_failed() -> None:
    evaluators = [{"type": "command", "name": "tests"}, {"type": "tool_used", "name": "used"}]
    calls = [call("write_file", path="a.py"), call("run_command", output="exit_code: 0")]
    run = failed_run(calls, results={"tests": True, "used": False}, evaluators=evaluators)
    assert stage_and_signals(run)[0] == FailureStage.UNDETERMINED


def test_plan_missing_signal() -> None:
    run = failed_run([], planner={"strategy": "plan_execute"})
    assert TraceSignal.PLAN_MISSING in stage_and_signals(run)[1]
    run.plan = ["1. do it"]
    assert TraceSignal.PLAN_MISSING not in stage_and_signals(run)[1]


@pytest.mark.parametrize("error", ["setup", "cancelled", "llm.refusal", "llm.rate_limit", "boom"])
def test_failures_the_trace_cannot_explain_are_not_diagnosed(error: str) -> None:
    run = failed_run([call("read_file", path="a.py")], error=error)
    assert diagnose_run(run) is None
    failure = classify_run(run)
    assert failure is not None
    assert failure.diagnosis is None


def test_passed_run_is_not_diagnosed() -> None:
    assert diagnose_run(failed_run([], results={"tests": True, "answer": True})) is None


def test_unknown_tools_do_not_count_as_exploring_or_changing() -> None:
    run = failed_run([call("plugin_tool")])
    diagnosis = diagnose_run(run, phases={})
    assert diagnosis is not None
    assert diagnosis.phases == {"other": 1}
    assert diagnosis.stage == FailureStage.PLANNING  # nothing changed, no command run


def test_every_stage_and_signal_is_described() -> None:
    assert set(STAGE_DESCRIPTIONS) == set(FailureStage)
    assert set(SIGNAL_DESCRIPTIONS) == set(TraceSignal)


# ------------------------------------------------------- analysis + proposal
def _analysis(runs: list[Run]) -> FailureAnalysis:
    from tests.unit.test_improvement import bench

    for index, run in enumerate(runs, 1):
        run.labels["repeat"] = str(index)
    return analyze(bench(runs), {r.id: r for r in runs})


def test_analysis_aggregates_stages_and_signals() -> None:
    reads = [call("read_file", path="a.py")]
    loop = [call("write_file", path="a.py")] + [call("run_command", command="pytest")] * 3
    analysis = _analysis(
        [
            failed_run(reads),
            failed_run(reads, error="max_steps"),
            failed_run(loop, error="max_steps"),
            failed_run([], error="setup"),
        ]
    )
    assert analysis.failed == 4
    assert analysis.stages == {"planning": 2, "execution": 1}  # the setup failure is omitted
    assert analysis.signals["read_only"] == 2
    assert analysis.signals["repeated_call"] == 1
    assert [f.diagnosis is None for f in analysis.failures] == [False, False, False, True]


def test_analysis_without_diagnosis_fields_still_loads() -> None:
    """Cycles stored before the diagnosis existed have no stage data."""
    data = _analysis([failed_run([])]).model_dump(mode="json")
    del data["stages"], data["signals"], data["failures"][0]["diagnosis"]
    loaded = FailureAnalysis.model_validate(data)
    assert loaded.stages == {}
    assert loaded.failures[0].diagnosis is None


def test_proposal_notes_qualify_limit_changes_with_the_diagnosis() -> None:
    loop = [call("write_file", path="a.py")] + [call("run_command", command="pytest")] * 3
    runs = [failed_run(loop, error="max_steps", limits={"max_steps": 5}), failed_run([])]
    analysis = _analysis(runs)
    suite = BenchmarkSuite.model_validate(
        {
            "id": "s",
            "name": "S",
            "defaults": {"max_steps": 20},
            "tasks": [
                {"id": "t1", "goal": "one", "evaluators": [{"type": "completed"}]},
                {"id": "t2", "goal": "two", "evaluators": [{"type": "completed"}]},
            ],
        }
    )
    proposal = propose(analysis, runs[0].config, suite)
    assert any(c.path == "limits.max_steps" and c.value == 20 for c in proposal.changes)
    assert analysis.categories[FailureCategory.STEP_LIMIT.value] == 1
    notes = "\n".join(proposal.notes)
    assert "repeating an identical call" in notes
    assert runs[0].id in notes
    assert "never attempted a change" in notes
    assert runs[1].id in notes
