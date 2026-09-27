"""CI regression gate: decide whether a candidate benchmark may replace a baseline.

The gate compares two benchmark reports (``BenchmarkReport``: a stored
benchmark run or a report JSON file written by ``agentforge bench report``) of
the same suite and returns one of three verdicts, each with a fixed exit code:

* ``pass`` (0) - comparable, and no threshold is violated;
* ``regression`` (1) - comparable, and at least one threshold is violated;
* ``error`` (2) - the gate cannot decide: the inputs are missing, invalid or
  not comparable, a benchmark did not finish, or a run failed for an
  infrastructure reason. An error is never a pass.

It evaluates nothing itself: pass/fail and scores come from the evaluators
that produced the reports, failure categories from the failure analysis.
Defaults are conservative: any drop in the overall pass rate, in any task's
pass rate or in the mean score is a regression.
"""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum

from pydantic import BaseModel, Field

from agentforge.benchmarks.report import BenchmarkReport, TaskRunRecord

# Failure categories that are problems of the benchmark or environment, not of
# the agent: a run that ends in one of them was not a valid evaluation.
INFRASTRUCTURE_CATEGORIES = frozenset({"setup", "internal", "cancelled", "missing_record"})
_EPSILON = 1e-9


class GateVerdict(StrEnum):
    PASS = "pass"  # noqa: S105 - verdict name, not a secret
    REGRESSION = "regression"
    ERROR = "error"


EXIT_CODES = {GateVerdict.PASS: 0, GateVerdict.REGRESSION: 1, GateVerdict.ERROR: 2}


class GateThresholds(BaseModel):
    """Allowed drops (absolute, 0-1) from baseline to candidate; 0 = no drop allowed."""

    max_pass_rate_drop: float = Field(default=0.0, ge=0.0, le=1.0)
    max_task_pass_rate_drop: float = Field(default=0.0, ge=0.0, le=1.0)
    max_mean_score_drop: float = Field(default=0.0, ge=0.0, le=1.0)
    min_pass_rate: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Absolute floor for the candidate's pass rate."
    )


class GateSide(BaseModel):
    benchmark_run_id: str
    agent_name: str
    agent_version: int | None = None
    provider: str
    model: str
    runs: int
    passed: int
    pass_rate: float
    mean_score: float


class TaskGate(BaseModel):
    task_id: str
    baseline_passed: int
    baseline_runs: int
    candidate_passed: int
    candidate_runs: int
    baseline_pass_rate: float
    candidate_pass_rate: float
    delta: float


class GateResult(BaseModel):
    verdict: GateVerdict
    exit_code: int
    suite_id: str | None = None
    suite_version: str | None = None
    result_class: str | None = None
    baseline: GateSide | None = None
    candidate: GateSide | None = None
    thresholds: GateThresholds
    tasks: list[TaskGate] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    regressions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def gate_error(message: str, thresholds: GateThresholds | None = None) -> GateResult:
    """A gate result for inputs that could not even be loaded."""
    return GateResult(
        verdict=GateVerdict.ERROR,
        exit_code=EXIT_CODES[GateVerdict.ERROR],
        thresholds=thresholds or GateThresholds(),
        errors=[message],
    )


def _side(report: BenchmarkReport) -> GateSide:
    runs = report.runs
    passed = sum(1 for r in runs if r.success)
    return GateSide(
        benchmark_run_id=report.benchmark_run_id,
        agent_name=report.agent_name,
        agent_version=report.agent_version,
        provider=report.provider,
        model=report.model,
        runs=len(runs),
        passed=passed,
        pass_rate=round(passed / len(runs), 4) if runs else 0.0,
        mean_score=round(sum(r.score for r in runs) / len(runs), 4) if runs else 0.0,
    )


def _rate(report: BenchmarkReport) -> float:
    return sum(1 for r in report.runs if r.success) / len(report.runs)


def _mean_score(report: BenchmarkReport) -> float:
    return sum(r.score for r in report.runs) / len(report.runs)


def _by_task(runs: list[TaskRunRecord]) -> dict[str, list[TaskRunRecord]]:
    grouped: dict[str, list[TaskRunRecord]] = defaultdict(list)
    for record in runs:
        grouped[record.task_id].append(record)
    return grouped


def _infrastructure_failures(label: str, report: BenchmarkReport) -> list[str]:
    problems = []
    for r in sorted(report.runs, key=lambda r: (r.task_id, r.repeat)):
        category = r.failure_category
        if r.status in ("missing", "cancelled"):
            category = category or ("missing_record" if r.status == "missing" else "cancelled")
        if category in INFRASTRUCTURE_CATEGORIES:
            detail = f": {r.error}" if r.error else ""
            problems.append(
                f"{label} run {r.task_id}#{r.repeat} failed for an infrastructure reason "
                f"({category}){detail}"
            )
    return problems


def evaluate_gate(
    baseline: BenchmarkReport,
    candidate: BenchmarkReport,
    thresholds: GateThresholds | None = None,
) -> GateResult:
    """Compare ``candidate`` with ``baseline`` under ``thresholds`` (deterministic)."""
    thresholds = thresholds or GateThresholds()
    errors: list[str] = []
    regressions: list[str] = []
    notes: list[str] = []

    # --- can the two be compared at all?
    if (baseline.suite_id, baseline.suite_version) != (candidate.suite_id, candidate.suite_version):
        errors.append(
            f"different suites: baseline {baseline.suite_id}@{baseline.suite_version}, "
            f"candidate {candidate.suite_id}@{candidate.suite_version}"
        )
    if baseline.suite_digest and candidate.suite_digest:
        if baseline.suite_digest != candidate.suite_digest:
            errors.append("the task definitions differ (suite digests do not match)")
    else:
        notes.append(
            "task definitions not verified: a report predates suite digests (suite id and "
            "version were compared)"
        )
    if baseline.result_class != candidate.result_class:
        errors.append(
            f"different result classes: baseline {baseline.result_class.value}, candidate "
            f"{candidate.result_class.value} (offline and real results are never compared)"
        )
    for label, report in (("baseline", baseline), ("candidate", candidate)):
        if report.status != "succeeded":
            errors.append(f"{label} benchmark did not finish (status {report.status})")
        if not report.runs:
            errors.append(f"{label} benchmark has no runs")
        errors.extend(_infrastructure_failures(label, report))
    base_tasks, cand_tasks = _by_task(baseline.runs), _by_task(candidate.runs)
    if set(base_tasks) != set(cand_tasks):
        missing = sorted(set(base_tasks) - set(cand_tasks))
        extra = sorted(set(cand_tasks) - set(base_tasks))
        detail = "; ".join(
            part
            for part in (
                f"missing in candidate: {', '.join(missing)}" if missing else "",
                f"not in baseline: {', '.join(extra)}" if extra else "",
            )
            if part
        )
        errors.append(f"the task sets differ ({detail})")
    unknown = sum(1 for r in candidate.runs if not r.success and r.failure_category is None)
    if unknown:
        notes.append(
            f"{unknown} failed candidate run(s) have no failure category (report predates it); "
            "they count as agent failures"
        )

    base_side, cand_side = _side(baseline), _side(candidate)
    tasks: list[TaskGate] = []
    for task_id in sorted(set(base_tasks) & set(cand_tasks)):
        b, c = base_tasks[task_id], cand_tasks[task_id]
        b_rate = sum(1 for r in b if r.success) / len(b)
        c_rate = sum(1 for r in c if r.success) / len(c)
        tasks.append(
            TaskGate(
                task_id=task_id,
                baseline_passed=sum(1 for r in b if r.success),
                baseline_runs=len(b),
                candidate_passed=sum(1 for r in c if r.success),
                candidate_runs=len(c),
                baseline_pass_rate=round(b_rate, 4),
                candidate_pass_rate=round(c_rate, 4),
                delta=round(c_rate - b_rate, 4),
            )
        )

    if not errors:
        # --- thresholds (only meaningful for a comparable pair). Compared on exact
        # rates; the rounded values are for display only.
        drop = _rate(baseline) - _rate(candidate)
        if drop > thresholds.max_pass_rate_drop + _EPSILON:
            regressions.append(
                f"pass rate dropped by {drop:.4f} ({base_side.pass_rate:.4f} -> "
                f"{cand_side.pass_rate:.4f}; allowed {thresholds.max_pass_rate_drop:.4f})"
            )
        for task in tasks:
            b, c = base_tasks[task.task_id], cand_tasks[task.task_id]
            task_drop = sum(r.success for r in b) / len(b) - sum(r.success for r in c) / len(c)
            if task_drop > thresholds.max_task_pass_rate_drop + _EPSILON:
                regressions.append(
                    f"task {task.task_id}: pass rate dropped by {task_drop:.4f} "
                    f"({task.baseline_passed}/{task.baseline_runs} -> "
                    f"{task.candidate_passed}/{task.candidate_runs}; allowed "
                    f"{thresholds.max_task_pass_rate_drop:.4f})"
                )
        score_drop = _mean_score(baseline) - _mean_score(candidate)
        if score_drop > thresholds.max_mean_score_drop + _EPSILON:
            regressions.append(
                f"mean score dropped by {score_drop:.4f} ({base_side.mean_score:.4f} -> "
                f"{cand_side.mean_score:.4f}; allowed {thresholds.max_mean_score_drop:.4f})"
            )
        if (
            thresholds.min_pass_rate is not None
            and _rate(candidate) + _EPSILON < thresholds.min_pass_rate
        ):
            regressions.append(
                f"pass rate {cand_side.pass_rate:.4f} is below the required minimum "
                f"{thresholds.min_pass_rate:.4f}"
            )

    if errors:
        verdict = GateVerdict.ERROR
    elif regressions:
        verdict = GateVerdict.REGRESSION
    else:
        verdict = GateVerdict.PASS
    return GateResult(
        verdict=verdict,
        exit_code=EXIT_CODES[verdict],
        suite_id=baseline.suite_id,
        suite_version=baseline.suite_version,
        result_class=baseline.result_class.value,
        baseline=base_side,
        candidate=cand_side,
        thresholds=thresholds,
        tasks=tasks,
        errors=errors,
        regressions=regressions,
        notes=notes,
    )


def render_gate(result: GateResult) -> str:
    """Human-readable, deterministic summary (no timestamps, stable ordering)."""
    lines = [f"REGRESSION GATE: {result.verdict.value.upper()} (exit {result.exit_code})"]
    if result.suite_id:
        lines.append(
            f"suite {result.suite_id}@{result.suite_version}  results {result.result_class}"
        )
    for label, side in (("baseline", result.baseline), ("candidate", result.candidate)):
        if side is not None:
            version = f" v{side.agent_version}" if side.agent_version is not None else ""
            lines.append(
                f"{label:<9} {side.benchmark_run_id}  {side.agent_name}{version}  "
                f"{side.provider}/{side.model}  pass {side.passed}/{side.runs} "
                f"({side.pass_rate:.4f})  mean score {side.mean_score:.4f}"
            )
    t = result.thresholds
    lines.append(
        f"thresholds: max pass-rate drop {t.max_pass_rate_drop:.4f}, max task pass-rate drop "
        f"{t.max_task_pass_rate_drop:.4f}, max mean-score drop {t.max_mean_score_drop:.4f}, "
        f"min pass rate {'none' if t.min_pass_rate is None else f'{t.min_pass_rate:.4f}'}"
    )
    if result.tasks:
        lines.append("tasks:")
        for task in result.tasks:
            lines.append(
                f"  {task.task_id:<32} {task.baseline_passed}/{task.baseline_runs} -> "
                f"{task.candidate_passed}/{task.candidate_runs}  ({task.delta:+.4f})"
            )
    for heading, items in (
        ("errors", result.errors),
        ("regressions", result.regressions),
        ("notes", result.notes),
    ):
        if items:
            lines.append(f"{heading}:")
            lines.extend(f"  - {item}" for item in items)
    return "\n".join(lines)


__all__ = [
    "EXIT_CODES",
    "INFRASTRUCTURE_CATEGORIES",
    "GateResult",
    "GateThresholds",
    "GateVerdict",
    "evaluate_gate",
    "gate_error",
    "render_gate",
]
