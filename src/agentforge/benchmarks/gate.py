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

Opt-in policies: token and latency budgets, a minimum number of runs per task
(``min_repeats``), a per-check pass-rate threshold, failure categories that
are never tolerated in the candidate, and a baseline pooled from several
accepted reports instead of a single one.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

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
    max_token_increase: float | None = Field(
        default=None,
        ge=0.0,
        description="Opt-in budget: allowed relative increase of the tokens one pass over the "
        "suite uses (0.25 = +25%; repeats are averaged per task). If set and either report "
        "lacks token usage for any run, the gate cannot decide.",
    )
    max_duration_increase: float | None = Field(
        default=None,
        ge=0.0,
        description="Opt-in budget: allowed relative increase of mean run duration. Wall-clock "
        "time is noisy; use a generous value. Missing durations make the gate unable to decide.",
    )
    min_repeats: int | None = Field(
        default=None,
        ge=1,
        description="Opt-in: every task needs at least this many runs in the baseline (pooled, "
        "if several are given) and in the candidate; otherwise the gate cannot decide.",
    )
    max_check_pass_rate_drop: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Opt-in: allowed drop of any single check's pass rate within a task "
        "(absolute, 0-1). A run that did not record a check did not pass it.",
    )
    fail_on_categories: list[str] = Field(
        default_factory=list,
        description="Opt-in: failure categories that are never tolerated - any candidate run "
        "that failed with one of them is a regression, whatever the baseline did.",
    )

    @field_validator("fail_on_categories")
    @classmethod
    def _known_categories(cls, value: list[str]) -> list[str]:
        from agentforge.improvement.analysis import FailureCategory  # avoid an import cycle

        known = {c.value for c in FailureCategory}
        unknown = sorted(set(value) - known)
        if unknown:
            raise ValueError(
                f"unknown failure categories: {', '.join(unknown)} "
                f"(known: {', '.join(sorted(known))})"
            )
        return sorted(set(value))


class GateSide(BaseModel):
    benchmark_run_id: str
    benchmark_run_ids: list[str] = Field(
        default_factory=list,
        description="All reports behind this side: several for a pooled baseline "
        "(benchmark_run_id then joins them with '+').",
    )
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
        benchmark_run_ids=report.benchmark_run_id.split("+"),
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


def _run_tokens(record: TaskRunRecord) -> float | None:
    if record.input_tokens is None or record.output_tokens is None:
        return None
    return float(record.input_tokens + record.output_tokens)


def _run_duration(record: TaskRunRecord) -> float | None:
    return record.duration_seconds


def _per_task_means(
    report: BenchmarkReport, value: Callable[[TaskRunRecord], float | None]
) -> list[float] | None:
    """Mean of ``value`` over each task's runs; ``None`` unless every run has a value.

    Averaging per task first keeps reports with different numbers of repeats
    comparable (three repeats do not look like three times the usage).
    """
    means = []
    for records in _by_task(report.runs).values():
        values = [value(r) for r in records]
        if any(v is None for v in values):
            return None
        means.append(sum(v or 0.0 for v in values) / len(values))
    return means or None


def _suite_pass_tokens(report: BenchmarkReport) -> float | None:
    """Tokens one pass over the suite uses (the total, when every task ran once)."""
    means = _per_task_means(report, _run_tokens)
    return None if means is None else sum(means)


def _mean_duration(report: BenchmarkReport) -> float | None:
    means = _per_task_means(report, _run_duration)
    return None if means is None else sum(means) / len(means)


def _budget_check(
    name: str, unit: str, values: tuple[float | None, float | None], allowed: float
) -> tuple[str | None, str | None]:
    """Return ``(error, regression)`` for a relative budget; at most one is set."""
    base, cand = values
    if base is None or cand is None:
        return f"{name} budget is set but {name} is not recorded for every run", None
    if base <= 0:
        return f"{name} budget cannot be applied: the baseline {name} is zero", None
    if cand > base * (1 + allowed) + _EPSILON:
        return None, (
            f"{name} increased by {(cand - base) / base:.1%} ({base:.4g} -> {cand:.4g} {unit}; "
            f"allowed {allowed:.1%})"
        )
    return None, None


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


def _comparability_errors(
    label: str, baseline: BenchmarkReport, candidate: BenchmarkReport
) -> list[str]:
    """Why one baseline report cannot be compared with the candidate (empty if it can)."""
    errors = []
    if (baseline.suite_id, baseline.suite_version) != (candidate.suite_id, candidate.suite_version):
        errors.append(
            f"different suites: {label} {baseline.suite_id}@{baseline.suite_version}, "
            f"candidate {candidate.suite_id}@{candidate.suite_version}"
        )
    if (
        baseline.suite_digest
        and candidate.suite_digest
        and baseline.suite_digest != candidate.suite_digest
    ):
        suffix = "" if label == "baseline" else f" ({label})"
        errors.append(f"the task definitions differ (suite digests do not match){suffix}")
    if baseline.result_class != candidate.result_class:
        errors.append(
            f"different result classes: {label} {baseline.result_class.value}, candidate "
            f"{candidate.result_class.value} (offline and real results are never compared)"
        )
    base_ids = {r.task_id for r in baseline.runs}
    cand_ids = {r.task_id for r in candidate.runs}
    if base_ids != cand_ids:
        missing, extra = sorted(base_ids - cand_ids), sorted(cand_ids - base_ids)
        detail = "; ".join(
            part
            for part in (
                f"missing in candidate: {', '.join(missing)}" if missing else "",
                f"not in {label}: {', '.join(extra)}" if extra else "",
            )
            if part
        )
        errors.append(f"the task sets differ ({detail})")
    return errors


def _repeat_errors(
    minimum: int, sides: tuple[tuple[str, dict[str, list[TaskRunRecord]]], ...]
) -> list[str]:
    errors = []
    for label, tasks in sides:
        short = [f"{t} ({len(tasks[t])})" for t in sorted(tasks) if len(tasks[t]) < minimum]
        if short:
            errors.append(
                f"min repeats {minimum} not met: {label} has fewer runs for {', '.join(short)}"
            )
    return errors


def _check_rates(records: list[TaskRunRecord]) -> dict[str, float]:
    """Pass rate of each named check over ``records``; a run without it did not pass it."""
    passed: dict[str, int] = {}
    for record in records:
        outcome: dict[str, bool] = {}
        for check in record.checks:
            outcome[check.name] = outcome.get(check.name, True) and check.passed
        for name, ok in outcome.items():
            passed[name] = passed.get(name, 0) + (1 if ok else 0)
    return {name: count / len(records) for name, count in passed.items()}


def _check_regressions(
    allowed: float,
    base_tasks: dict[str, list[TaskRunRecord]],
    cand_tasks: dict[str, list[TaskRunRecord]],
) -> list[str]:
    regressions = []
    for task_id in sorted(set(base_tasks) & set(cand_tasks)):
        base_rates, cand_rates = (
            _check_rates(base_tasks[task_id]),
            _check_rates(cand_tasks[task_id]),
        )
        for name in sorted(base_rates):
            drop = base_rates[name] - cand_rates.get(name, 0.0)
            if drop > allowed + _EPSILON:
                regressions.append(
                    f"task {task_id}: check {name!r} pass rate dropped by {drop:.4f} "
                    f"({base_rates[name]:.4f} -> {cand_rates.get(name, 0.0):.4f}; "
                    f"allowed {allowed:.4f})"
                )
    return regressions


def _category_regressions(categories: list[str], candidate: BenchmarkReport) -> list[str]:
    return [
        f"candidate run {r.task_id}#{r.repeat} failed with the category "
        f"{r.failure_category!r}, which is not tolerated"
        for r in sorted(candidate.runs, key=lambda r: (r.task_id, r.repeat))
        if not r.success and r.failure_category in categories
    ]


def evaluate_gate(
    baseline: BenchmarkReport | Sequence[BenchmarkReport],
    candidate: BenchmarkReport,
    thresholds: GateThresholds | None = None,
) -> GateResult:
    """Compare ``candidate`` with ``baseline`` under ``thresholds`` (deterministic).

    ``baseline`` may be several reports of the same suite (e.g. the last accepted
    runs): they are pooled, so every rate is computed over all their runs.
    """
    thresholds = thresholds or GateThresholds()
    baselines = [baseline] if isinstance(baseline, BenchmarkReport) else list(baseline)
    if not baselines:
        return gate_error("no baseline given", thresholds)
    errors: list[str] = []
    regressions: list[str] = []
    notes: list[str] = []

    # --- can they be compared at all?
    pooled = len(baselines) > 1
    labels = [f"baseline {b.benchmark_run_id}" if pooled else "baseline" for b in baselines]
    ids = [b.benchmark_run_id for b in baselines]
    if len(set(ids)) != len(ids):
        errors.append("the same baseline was given more than once")
    if pooled and candidate.benchmark_run_id in ids:
        errors.append("the candidate is one of the pooled baselines")
    for label, report in zip(labels, baselines, strict=True):
        errors.extend(_comparability_errors(label, report, candidate))
    if not all(b.suite_digest for b in baselines) or not candidate.suite_digest:
        notes.append(
            "task definitions not verified: a report predates suite digests (suite id and "
            "version were compared)"
        )
    for label, report in (*zip(labels, baselines, strict=True), ("candidate", candidate)):
        if report.status != "succeeded":
            errors.append(f"{label} benchmark did not finish (status {report.status})")
        if not report.runs:
            errors.append(f"{label} benchmark has no runs")
        errors.extend(_infrastructure_failures(label, report))
    if pooled:
        # The newest (last given) report names the side; the runs of all are pooled.
        baseline = baselines[-1].model_copy(
            update={
                "runs": [r for b in baselines for r in b.runs],
                "benchmark_run_id": "+".join(ids),
            }
        )
        notes.append(
            f"baseline pooled from {len(baselines)} reports ({len(baseline.runs)} runs); rates "
            "are computed over all of them"
        )
        identities = {(b.agent_name, b.agent_version, b.provider, b.model) for b in baselines}
        if len(identities) > 1:
            notes.append(
                "the pooled baselines come from different agent versions or models; the "
                "baseline line shows the last one given"
            )
    else:
        baseline = baselines[0]
    base_tasks, cand_tasks = _by_task(baseline.runs), _by_task(candidate.runs)
    if thresholds.min_repeats is not None:
        errors.extend(
            _repeat_errors(
                thresholds.min_repeats, (("baseline", base_tasks), ("candidate", cand_tasks))
            )
        )
    unknown = sum(1 for r in candidate.runs if not r.success and r.failure_category is None)
    if unknown:
        notes.append(
            f"{unknown} failed candidate run(s) have no failure category (report predates it); "
            "they count as agent failures"
        )

    budget_regressions: list[str] = []
    budgets = (
        ("tokens per suite pass", "tokens", thresholds.max_token_increase, _suite_pass_tokens),
        ("mean duration", "s", thresholds.max_duration_increase, _mean_duration),
    )
    for name, unit, allowed, measure in budgets:
        if allowed is not None:
            error, regression = _budget_check(
                name, unit, (measure(baseline), measure(candidate)), allowed
            )
            if error:
                errors.append(error)
            if regression:
                budget_regressions.append(regression)

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
        regressions.extend(budget_regressions)
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
        if thresholds.max_check_pass_rate_drop is not None:
            regressions.extend(
                _check_regressions(thresholds.max_check_pass_rate_drop, base_tasks, cand_tasks)
            )
        regressions.extend(_category_regressions(thresholds.fail_on_categories, candidate))

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


def _opt(value: float | None) -> str:
    return "none" if value is None else f"{value:.1%}"


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
        f"min pass rate {'none' if t.min_pass_rate is None else f'{t.min_pass_rate:.4f}'}, "
        f"max token increase {_opt(t.max_token_increase)}, "
        f"max duration increase {_opt(t.max_duration_increase)}"
    )
    policies = [
        f"min repeats {t.min_repeats}" if t.min_repeats is not None else "",
        f"max check pass-rate drop {t.max_check_pass_rate_drop:.4f}"
        if t.max_check_pass_rate_drop is not None
        else "",
        f"fail on categories {', '.join(t.fail_on_categories)}" if t.fail_on_categories else "",
    ]
    if any(policies):
        lines.append("policies: " + ", ".join(p for p in policies if p))
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
