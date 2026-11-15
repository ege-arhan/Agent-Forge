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
from agentforge.benchmarks.report import (
    BenchmarkReport,
    CheckResult,
    ReportSummary,
    TaskRunRecord,
)
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


def _usage_report(tokens: list[tuple[int | None, int | None]], **extra: Any) -> BenchmarkReport:
    runs = [
        record(f"t{i}", True, input_tokens=i_tok, output_tokens=o_tok, duration_seconds=d)
        for i, (i_tok, o_tok) in enumerate(tokens)
        for d in [extra.pop("duration", 10.0) if i == 0 else 10.0]
    ]
    return report(runs, **extra)


def test_budgets_are_opt_in() -> None:
    base = _usage_report([(100, 100)])
    cand = _usage_report([(1000, 1000)], bench_id="bench_c")
    assert evaluate_gate(base, cand).verdict == GateVerdict.PASS


def test_token_budget_regression_and_boundary() -> None:
    base = _usage_report([(100, 100), (100, 100)])
    over = _usage_report([(150, 100), (100, 100)], bench_id="c")  # +25% exactly... 450 vs 400
    ok = evaluate_gate(base, over, GateThresholds(max_token_increase=0.125))
    assert ok.verdict == GateVerdict.PASS  # exactly at the limit is allowed
    bad = evaluate_gate(base, over, GateThresholds(max_token_increase=0.10))
    assert bad.verdict == GateVerdict.REGRESSION
    assert "tokens per suite pass increased by 12.5%" in bad.regressions[0]


def test_token_budget_missing_usage_cannot_decide() -> None:
    base = _usage_report([(100, 100)])
    cand = _usage_report([(None, None)], bench_id="c")
    result = evaluate_gate(base, cand, GateThresholds(max_token_increase=0.5))
    assert result.verdict == GateVerdict.ERROR
    assert "not recorded" in result.errors[0]


def test_duration_budget() -> None:
    base = _usage_report([(1, 1)])
    slow = _usage_report([(1, 1)], bench_id="c", duration=30.0)
    result = evaluate_gate(base, slow, GateThresholds(max_duration_increase=0.5))
    assert result.verdict == GateVerdict.REGRESSION
    assert "mean duration" in result.regressions[0]
    assert evaluate_gate(base, slow, GateThresholds(max_duration_increase=2.0)).verdict == (
        GateVerdict.PASS
    )


def test_budget_zero_baseline_cannot_decide() -> None:
    base = _usage_report([(0, 0)])
    result = evaluate_gate(base, base, GateThresholds(max_token_increase=0.5))
    assert result.verdict == GateVerdict.ERROR


def test_budgets_not_applied_to_incomparable_reports() -> None:
    base = _usage_report([(100, 100)])
    cand = _usage_report([(1000, 1000)], bench_id="c", suite_id="other")
    result = evaluate_gate(base, cand, GateThresholds(max_token_increase=0.1))
    assert result.verdict == GateVerdict.ERROR
    assert result.regressions == []


def test_budgets_compare_reports_with_different_repeats_fairly() -> None:
    """Regression: three repeats used to look like three times the tokens of one."""

    def usage(repeats: int, tokens: int, bench_id: str) -> BenchmarkReport:
        return report(
            [
                record(task, True, repeat=n, input_tokens=tokens, output_tokens=0)
                for task in ("a", "b")
                for n in range(1, repeats + 1)
            ],
            bench_id=bench_id,
        )

    limits = GateThresholds(max_token_increase=0.1)
    same_usage = evaluate_gate(usage(1, 100, "b"), usage(3, 100, "c"), limits)
    assert same_usage.verdict == GateVerdict.PASS
    # ... and a real increase is not hidden by a baseline with more repeats.
    hidden = evaluate_gate(usage(3, 100, "b"), usage(1, 200, "c"), limits)
    assert hidden.verdict == GateVerdict.REGRESSION
    assert "increased by 100.0% (200 -> 400 tokens" in hidden.regressions[0]


# --- opt-in policies: required repeats, per-check thresholds, categories, pooled baselines


def repeated(task: str, outcomes: list[bool], **extra: Any) -> list[TaskRunRecord]:
    return [record(task, ok, repeat=n, **extra) for n, ok in enumerate(outcomes, 1)]


def test_min_repeats_cannot_decide_on_too_few_runs() -> None:
    three = report(repeated("a", [True] * 3) + repeated("b", [True] * 3), bench_id="b3")
    one = report(repeated("a", [True]) + repeated("b", [True] * 3), bench_id="c1")
    assert evaluate_gate(three, one).verdict == GateVerdict.PASS  # opt-in
    result = evaluate_gate(three, one, GateThresholds(min_repeats=3))
    assert (result.verdict, result.exit_code) == (GateVerdict.ERROR, 2)
    assert result.errors == ["min repeats 3 not met: candidate has fewer runs for a (1)"]
    assert evaluate_gate(three, three, GateThresholds(min_repeats=3)).verdict == GateVerdict.PASS
    both = evaluate_gate(one, one, GateThresholds(min_repeats=2))
    assert [e.split(":")[1].split(" has")[0].strip() for e in both.errors] == [
        "baseline",
        "candidate",
    ]
    assert "policies: min repeats 3" in render_gate(result)


def checked(task: str, checks: dict[str, bool], repeat: int = 1, **extra: Any) -> TaskRunRecord:
    results = [
        CheckResult(name=name, passed=ok, score=1.0 if ok else 0.0, required=False)
        for name, ok in checks.items()
    ]
    return record(task, True, repeat=repeat, checks=results, **extra)


def test_check_threshold_catches_a_check_the_task_verdict_hides() -> None:
    base = report([checked("a", {"tests": True, "hidden": True})], bench_id="b")
    cand = report([checked("a", {"tests": True, "hidden": False})], bench_id="c")
    # The task still passes and the score is unchanged, so the default gate passes.
    assert evaluate_gate(base, cand).verdict == GateVerdict.PASS
    result = evaluate_gate(base, cand, GateThresholds(max_check_pass_rate_drop=0.0))
    assert result.verdict == GateVerdict.REGRESSION
    assert result.regressions == [
        "task a: check 'hidden' pass rate dropped by 1.0000 (1.0000 -> 0.0000; allowed 0.0000)"
    ]
    assert evaluate_gate(base, base, GateThresholds(max_check_pass_rate_drop=0.0)).verdict == (
        GateVerdict.PASS
    )


def test_check_threshold_uses_rates_over_repeats_and_counts_missing_checks_as_failed() -> None:
    base = report(
        [checked("a", {"hidden": True}, n) for n in (1, 2, 3, 4)], bench_id="b", repeats=4
    )
    cand = report(
        [checked("a", {"hidden": n != 1}, n) for n in (1, 2, 3, 4)], bench_id="c", repeats=4
    )
    assert evaluate_gate(base, cand, GateThresholds(max_check_pass_rate_drop=0.25)).verdict == (
        GateVerdict.PASS
    )
    assert evaluate_gate(base, cand, GateThresholds(max_check_pass_rate_drop=0.2)).verdict == (
        GateVerdict.REGRESSION
    )
    # A candidate run that never recorded the check did not pass it.
    silent = report([checked("a", {}, n) for n in (1, 2, 3, 4)], bench_id="s", repeats=4)
    result = evaluate_gate(base, silent, GateThresholds(max_check_pass_rate_drop=0.5))
    assert result.verdict == GateVerdict.REGRESSION
    # A check that only the candidate has is not a regression.
    extra = report(
        [checked("a", {"hidden": True, "new": False}, n) for n in (1, 2, 3, 4)], bench_id="e"
    )
    assert evaluate_gate(base, extra, GateThresholds(max_check_pass_rate_drop=0.0)).verdict == (
        GateVerdict.PASS
    )


def test_fail_on_category_overrides_loose_thresholds() -> None:
    base = report(repeated("a", [True, True, True, False]), bench_id="b")
    cand = report(
        [*repeated("a", [True, True, True]), record("a", False, 4, failure_category="timeout")],
        bench_id="c",
    )
    loose = {"max_pass_rate_drop": 1.0, "max_task_pass_rate_drop": 1.0, "max_mean_score_drop": 1.0}
    assert evaluate_gate(base, cand, GateThresholds(**loose)).verdict == GateVerdict.PASS
    result = evaluate_gate(base, cand, GateThresholds(fail_on_categories=["timeout"], **loose))
    assert result.verdict == GateVerdict.REGRESSION
    assert result.regressions == [
        "candidate run a#4 failed with the category 'timeout', which is not tolerated"
    ]
    # Only the listed categories count, and only in the candidate.
    other = GateThresholds(fail_on_categories=["llm_refusal"], **loose)
    assert evaluate_gate(base, cand, other).verdict == GateVerdict.PASS
    reverse = evaluate_gate(cand, base, GateThresholds(fail_on_categories=["timeout"], **loose))
    assert reverse.verdict == GateVerdict.PASS


def test_fail_on_category_rejects_unknown_names() -> None:
    with pytest.raises(ValueError, match="unknown failure categories: timout"):
        GateThresholds(fail_on_categories=["timout"])
    assert GateThresholds(fail_on_categories=["timeout", "llm_error", "timeout"]).model_dump()[
        "fail_on_categories"
    ] == ["llm_error", "timeout"]


def test_pooled_baseline_uses_the_rate_over_all_accepted_runs() -> None:
    """A flaky task: one lucky baseline makes a normal candidate look like a regression."""
    lucky = report([record("a", True), record("b", True)], bench_id="b1")
    unlucky = report([record("a", True), record("b", False)], bench_id="b2")
    cand = report([record("a", True), record("b", False)], bench_id="c")
    assert evaluate_gate(lucky, cand).verdict == GateVerdict.REGRESSION
    tolerant = GateThresholds(
        max_pass_rate_drop=0.25, max_task_pass_rate_drop=0.5, max_mean_score_drop=0.25
    )
    assert evaluate_gate(lucky, cand, tolerant).verdict == GateVerdict.REGRESSION
    result = evaluate_gate([lucky, unlucky], cand, tolerant)
    assert result.verdict == GateVerdict.PASS
    assert result.baseline is not None
    assert (result.baseline.runs, result.baseline.passed) == (4, 3)
    assert result.baseline.benchmark_run_ids == ["b1", "b2"]
    assert result.baseline.benchmark_run_id == "b1+b2"
    [task_b] = [t for t in result.tasks if t.task_id == "b"]
    assert (task_b.baseline_passed, task_b.baseline_runs, task_b.delta) == (1, 2, -0.5)
    assert any("pooled from 2 reports (4 runs)" in n for n in result.notes)
    # Still strict by default: the pooled rate is 0.75 and the candidate's is 0.5.
    assert evaluate_gate([lucky, unlucky], cand).verdict == GateVerdict.REGRESSION
    # A single-element list is the plain gate.
    assert evaluate_gate([lucky], cand) == evaluate_gate(lucky, cand)
    assert evaluate_gate(lucky, cand).baseline.benchmark_run_ids == ["b1"]  # type: ignore[union-attr]


def test_pooled_baseline_counts_towards_min_repeats() -> None:
    runs = [report([record("a", True)], bench_id=f"b{i}") for i in range(3)]
    cand = report(repeated("a", [True, True, True]), bench_id="c")
    assert evaluate_gate(runs, cand, GateThresholds(min_repeats=3)).verdict == GateVerdict.PASS
    assert evaluate_gate(runs[:2], cand, GateThresholds(min_repeats=3)).verdict == (
        GateVerdict.ERROR
    )


@pytest.mark.parametrize(
    ("bad", "expected"),
    [
        ({"suite_version": "2"}, "different suites: baseline b2 suite@2"),
        ({"suite_digest": "other"}, "suite digests do not match) (baseline b2)"),
        ({"result_class": ResultClass.REAL}, "different result classes: baseline b2 real"),
        ({"status": "failed"}, "baseline b2 benchmark did not finish"),
    ],
)
def test_every_pooled_baseline_must_be_comparable(bad: dict[str, Any], expected: str) -> None:
    good = report([record("a", True)], bench_id="b1")
    cand = report([record("a", True)], bench_id="c")
    result = evaluate_gate([good, report([record("a", True)], bench_id="b2", **bad)], cand)
    assert result.verdict == GateVerdict.ERROR
    assert any(expected in e for e in result.errors), result.errors


def test_pooled_baseline_input_errors() -> None:
    good = report([record("a", True)], bench_id="b1")
    cand = report([record("a", True)], bench_id="c")
    assert evaluate_gate([], cand).errors == ["no baseline given"]
    assert "more than once" in evaluate_gate([good, good], cand).errors[0]
    assert "one of the pooled baselines" in evaluate_gate([good, cand], cand).errors[0]
    other_tasks = report([record("z", True)], bench_id="b2")
    result = evaluate_gate([good, other_tasks], cand)
    assert any("missing in candidate: z; not in baseline b2: a" in e for e in result.errors)
    infra = report([record("a", False, failure_category="setup")], bench_id="b3")
    assert any(
        e.startswith("baseline b3 run a#1 failed for an infrastructure reason")
        for e in evaluate_gate([good, infra], cand).errors
    )


def test_pooled_baseline_notes_mixed_agent_versions() -> None:
    v1 = report([record("a", True)], bench_id="b1", agent_version=1)
    v2 = report([record("a", True)], bench_id="b2", agent_version=2)
    result = evaluate_gate([v1, v2], report([record("a", True)], bench_id="c"))
    assert result.verdict == GateVerdict.PASS
    assert result.baseline is not None and result.baseline.agent_version == 2
    assert any("different agent versions or models" in n for n in result.notes)
