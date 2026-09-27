"""The CI regression gate's decision rules (pure: reports in, verdict out)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from agentforge.benchmarks.gate import (
    GateThresholds,
    GateVerdict,
    evaluate_gate,
    gate_error,
    render_gate,
)
from agentforge.benchmarks.report import BenchmarkReport, ReportSummary, TaskRunRecord
from agentforge.benchmarks.runner import ResultClass


def record(task: str, success: bool, repeat: int = 1, **extra: Any) -> TaskRunRecord:
    return TaskRunRecord(
        task_id=task,
        repeat=repeat,
        run_id=f"run_{task}_{repeat}",
        status=extra.pop("status", "succeeded" if success else "failed"),
        success=success,
        score=extra.pop("score", 1.0 if success else 0.0),
        failure_category=extra.pop("failure_category", None if success else "tests_failed"),
        **extra,
    )


def report(runs: list[TaskRunRecord], **extra: Any) -> BenchmarkReport:
    passed = sum(1 for r in runs if r.success)
    data: dict[str, Any] = {
        "result_class": ResultClass.OFFLINE,
        "benchmark_run_id": extra.pop("bench_id", "bench_x"),
        "status": "succeeded",
        "suite_id": "suite",
        "suite_name": "Suite",
        "suite_version": "1",
        "agent_name": "agent",
        "agent_version": 1,
        "provider": "scripted",
        "model": "m",
        "agentforge_version": "0.2.0",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "repeats": 1,
        "suite_digest": "d1",
        "summary": ReportSummary(
            runs=len(runs), passed=passed, pass_rate=passed / len(runs) if runs else 0.0
        ),
        "runs": runs,
    }
    data.update(extra)
    return BenchmarkReport.model_validate(data)


BASE = report([record("a", True), record("b", True), record("c", False)], bench_id="bench_base")


def test_no_regression_passes_with_exit_0() -> None:
    same = report([record("a", True), record("b", True), record("c", False)], bench_id="bench_new")
    result = evaluate_gate(BASE, same)
    assert (result.verdict, result.exit_code) == (GateVerdict.PASS, 0)
    assert result.errors == result.regressions == []
    better = report([record("a", True), record("b", True), record("c", True)])
    assert evaluate_gate(BASE, better).exit_code == 0


def test_regression_fails_with_exit_1() -> None:
    worse = report([record("a", True), record("b", False), record("c", False)])
    result = evaluate_gate(BASE, worse)
    assert (result.verdict, result.exit_code) == (GateVerdict.REGRESSION, 1)
    joined = "\n".join(result.regressions)
    assert "task b: pass rate dropped" in joined and "pass rate dropped by 0.3333" in joined
    assert "mean score dropped" in joined


def test_thresholds_are_configurable() -> None:
    worse = report([record("a", True), record("b", False), record("c", False)])
    lenient = GateThresholds(
        max_pass_rate_drop=0.34, max_task_pass_rate_drop=1.0, max_mean_score_drop=0.34
    )
    assert evaluate_gate(BASE, worse, lenient).verdict == GateVerdict.PASS
    only_task = GateThresholds(max_pass_rate_drop=1.0, max_mean_score_drop=1.0)
    assert evaluate_gate(BASE, worse, only_task).regressions == [
        "task b: pass rate dropped by 1.0000 (1/1 -> 0/1; allowed 0.0000)"
    ]
    # An absolute floor fails even without any drop.
    floor = GateThresholds(min_pass_rate=0.9)
    result = evaluate_gate(BASE, BASE, floor)
    assert result.verdict == GateVerdict.REGRESSION
    assert "below the required minimum 0.9000" in result.regressions[0]
    with pytest.raises(ValueError, match="less than or equal to 1"):
        GateThresholds(max_pass_rate_drop=1.5)


def test_score_drop_alone_is_a_regression() -> None:
    lower = report(
        [record("a", True, score=0.8), record("b", True), record("c", False)],
    )
    result = evaluate_gate(BASE, lower)
    assert result.verdict == GateVerdict.REGRESSION
    assert result.regressions == ["mean score dropped by 0.0667 (0.6667 -> 0.6000; allowed 0.0000)"]


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (report([record("a", True)], suite_id="other"), "different suites"),
        (
            report([record("a", True), record("b", True), record("c", False)], suite_digest="d2"),
            "task definitions differ",
        ),
        (
            report(
                [record("a", True), record("b", True), record("c", False)],
                result_class=ResultClass.REAL,
            ),
            "different result classes",
        ),
        (
            report([record("a", True), record("b", True)]),
            "task sets differ (missing in candidate: c)",
        ),
        (
            report([record("a", True), record("b", True), record("c", False)], status="failed"),
            "did not finish",
        ),
        (report([], suite_digest="d1"), "has no runs"),
    ],
)
def test_invalid_or_incomparable_inputs_are_errors(
    candidate: BenchmarkReport, message: str
) -> None:
    result = evaluate_gate(BASE, candidate)
    assert (result.verdict, result.exit_code) == (GateVerdict.ERROR, 2)
    assert any(message in e for e in result.errors), result.errors
    assert result.regressions == []  # thresholds are not applied to incomparable data


@pytest.mark.parametrize(
    "infra",
    [
        {"failure_category": "setup", "error": "setup failed: git not found"},
        {"failure_category": "internal"},
        {"status": "missing", "failure_category": None},
        {"status": "cancelled", "failure_category": None},
    ],
)
def test_infrastructure_failures_are_errors_not_passes(infra: dict[str, Any]) -> None:
    # Task c failed in the baseline too, so without the rule this would "pass".
    candidate = report([record("a", True), record("b", True), record("c", False, **infra)])
    result = evaluate_gate(BASE, candidate)
    assert result.verdict == GateVerdict.ERROR
    assert "infrastructure reason" in result.errors[0]


def test_infrastructure_failure_in_the_baseline_is_an_error() -> None:
    base = report([record("a", True), record("b", False, failure_category="setup")])
    cand = report([record("a", True), record("b", True)])
    assert evaluate_gate(base, cand).verdict == GateVerdict.ERROR


def test_reports_without_new_fields_still_compare_with_notes() -> None:
    old = report([record("a", True), record("b", False, failure_category=None)], suite_digest=None)
    result = evaluate_gate(old, old)
    assert result.verdict == GateVerdict.PASS
    assert any("predates suite digests" in n for n in result.notes)
    assert any("no failure category" in n for n in result.notes)


def test_output_is_deterministic() -> None:
    worse = report([record("c", False), record("b", False), record("a", True)])
    first = evaluate_gate(BASE, worse)
    second = evaluate_gate(BASE, worse)
    assert first.model_dump_json() == second.model_dump_json()
    assert render_gate(first) == render_gate(second)
    assert [t.task_id for t in first.tasks] == ["a", "b", "c"]
    text = render_gate(first)
    assert text.startswith("REGRESSION GATE: REGRESSION (exit 1)")
    assert "b                                1/1 -> 0/1  (-1.0000)" in text


def test_gate_error_helper() -> None:
    result = gate_error("baseline report file not found: x.json")
    assert (result.verdict, result.exit_code) == (GateVerdict.ERROR, 2)
    assert render_gate(result).splitlines()[0] == "REGRESSION GATE: ERROR (exit 2)"
