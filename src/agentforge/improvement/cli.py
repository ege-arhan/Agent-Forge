"""``agentforge improve ...`` subcommands (the agent improvement loop)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from agentforge.improvement.analysis import FailureAnalysis
    from agentforge.improvement.comparison import BenchmarkComparison
    from agentforge.improvement.cycle import ImprovementCycle

EXIT_OK = 0
EXIT_FAILED = 1


def register(sub: Any) -> None:
    improve = sub.add_parser(
        "improve",
        help="agent improvement loop: analyse, propose, apply, re-benchmark, compare",
    ).add_subparsers(dest="improve_cmd", required=True)

    analyze = improve.add_parser("analyze", help="failure analysis of a benchmark run")
    analyze.add_argument("benchmark_run_id")
    analyze.add_argument("--json", action="store_true")
    analyze.set_defaults(handler=cmd_analyze)

    propose = improve.add_parser("propose", help="record an improvement proposal (a new cycle)")
    propose.add_argument("benchmark_run_id", help="finished benchmark of a stored agent version")
    propose.add_argument(
        "--changes",
        metavar="FILE",
        help="YAML/JSON list of your own changes ({path, value, operation?, rationale?}) "
        "instead of the rule-based proposal",
    )
    propose.add_argument("--notes", default="")
    propose.add_argument("--json", action="store_true")
    propose.set_defaults(handler=cmd_propose)

    apply = improve.add_parser("apply", help="create the next agent version from a proposal")
    apply.add_argument("cycle_id")
    apply.add_argument("--change", action="append", help="only this change id (repeatable)")
    apply.set_defaults(handler=cmd_apply)

    evaluate = improve.add_parser(
        "evaluate", help="benchmark the new version on the baseline suite and compare"
    )
    evaluate.add_argument("cycle_id")
    evaluate.add_argument("-c", "--concurrency", type=int, default=1)
    evaluate.add_argument("--json", action="store_true")
    evaluate.set_defaults(handler=cmd_evaluate)

    reject = improve.add_parser(
        "reject", help="decline a proposal (reverts an applied version as a new version)"
    )
    reject.add_argument("cycle_id")
    reject.add_argument("--reason", default="")
    reject.set_defaults(handler=cmd_reject)

    run = improve.add_parser(
        "run", help="analyse → propose → apply → evaluate → compare, for up to N cycles"
    )
    run.add_argument("benchmark_run_id", help="baseline benchmark of a stored agent version")
    run.add_argument("-n", "--cycles", type=int, default=1)
    run.add_argument("-c", "--concurrency", type=int, default=1)
    run.add_argument("--json", action="store_true")
    run.set_defaults(handler=cmd_run)

    history = improve.add_parser("history", help="versions, benchmarks and improvement cycles")
    history.add_argument("agent", help="agent name or id")
    history.add_argument("--json", action="store_true")
    history.set_defaults(handler=cmd_history)


# ---------------------------------------------------------------- printing
def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def print_analysis(analysis: FailureAnalysis) -> None:
    print(
        f"benchmark {analysis.benchmark_run_id}  suite={analysis.suite_id}@{analysis.suite_version}"
        f"  agent={analysis.agent_name}"
        + (f" v{analysis.agent_version}" if analysis.agent_version is not None else "")
        + f"  results={analysis.result_class.value.upper()}"
    )
    print(f"runs {analysis.runs}  passed {analysis.passed}  failed {analysis.failed}")
    if analysis.categories:
        print("failure categories:")
        for category, count in analysis.categories.items():
            print(f"  {category:<22} {count}")
    for failure in analysis.failures:
        print(f"- {failure.task_id} #{failure.repeat} [{failure.category.value}] {failure.run_id}")
        for line in failure.evidence[:3]:
            print(f"    {line.splitlines()[0][:150]}")
    if analysis.tool_issues:
        issues = ", ".join(
            f"{tool}: " + "/".join(f"{k}={v}" for k, v in counts.items())
            for tool, counts in analysis.tool_issues.items()
        )
        print(f"tool issues: {issues}")


def print_cycle(cycle: ImprovementCycle) -> None:
    target = f" -> v{cycle.to_version}" if cycle.to_version is not None else ""
    print(
        f"improvement {cycle.id}  agent={cycle.agent_name} v{cycle.from_version}{target}"
        f"  status={cycle.status.value}  results={cycle.result_class.value.upper()}"
    )
    proposal = cycle.proposal
    if proposal.changes:
        print(f"proposal ({proposal.proposer}):")
        for change in proposal.changes:
            mark = "*" if change.id in cycle.applied_change_ids else " "
            value = str(change.value).replace("\n", " ")
            if len(value) > 90:
                value = value[:89] + "…"
            print(f" {mark}{change.id}  {change.path} {change.operation.value} {value}")
            if change.rationale:
                print(f"       why: {change.rationale}")
    else:
        print("proposal: no changes")
    for note in proposal.notes:
        print(f"  note: {note}")
    if cycle.comparison is not None:
        print_comparison(cycle.comparison)
    if cycle.reverted_to_version is not None:
        print(f"reverted: baseline config stored as v{cycle.reverted_to_version}")
    if cycle.error:
        print(f"error: {cycle.error}")


def print_comparison(comparison: BenchmarkComparison) -> None:
    b, c = comparison.baseline, comparison.candidate
    if not comparison.comparable or b is None or c is None:
        print("not comparable: " + "; ".join(comparison.reasons))
        return
    print(f"comparison ({comparison.suite_id}@{comparison.suite_version}):")
    for name, side in (("baseline", b), ("candidate", c)):
        ci = (
            f"{side.pass_rate_ci95[0]:.2f}-{side.pass_rate_ci95[1]:.2f}"
            if side.pass_rate_ci95
            else "-"
        )
        label = side.agent_name + (f" v{side.agent_version}" if side.agent_version else "")
        print(
            f"  {name:<9} {label:<28} pass {side.passed}/{side.runs} ({_pct(side.pass_rate)},"
            f" 95% CI {ci})  steps {side.mean_steps if side.mean_steps is not None else '-'}"
        )
    delta = comparison.pass_rate_delta or 0.0
    print(
        f"  verdict: {comparison.verdict.value.upper()}  (pass rate {delta:+.0%}"
        f"{', significant' if comparison.significant else ''})"
    )
    for task in comparison.tasks:
        if task.change.value != "unchanged":
            print(
                f"  {task.task_id:<28} {task.change.value:<9} "
                f"{task.baseline_passed}/{task.baseline_runs} -> "
                f"{task.candidate_passed}/{task.candidate_runs}"
            )
    for note in comparison.notes:
        print(f"  note: {note}")


def _dump(model: Any) -> None:
    print(json.dumps(model.model_dump(mode="json"), indent=2, default=str))


# ---------------------------------------------------------------- commands
async def _open() -> Any:
    from agentforge.settings import get_settings
    from agentforge.storage import Database

    db = Database(get_settings().resolved_database_url)
    await db.migrate()
    return db


async def cmd_analyze(args: argparse.Namespace) -> int:
    from agentforge.improvement.loop import ImprovementLoop

    db = await _open()
    try:
        analysis = await ImprovementLoop(db).analyze(args.benchmark_run_id)
    finally:
        await db.dispose()
    if args.json:
        _dump(analysis)
    else:
        print_analysis(analysis)
    return EXIT_OK


def _load_changes(path: str) -> list[Any]:
    from agentforge.improvement.proposal import ProposedChange

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else [raw]
    return [ProposedChange.model_validate(item) for item in items]


async def cmd_propose(args: argparse.Namespace) -> int:
    from agentforge.improvement.loop import ImprovementLoop

    changes = _load_changes(args.changes) if args.changes else None
    db = await _open()
    try:
        cycle = await ImprovementLoop(db).propose(
            args.benchmark_run_id, changes=changes, notes=args.notes
        )
    finally:
        await db.dispose()
    if args.json:
        _dump(cycle)
    else:
        print_cycle(cycle)
    return EXIT_OK


async def cmd_apply(args: argparse.Namespace) -> int:
    from agentforge.improvement.loop import ImprovementLoop

    db = await _open()
    try:
        cycle = await ImprovementLoop(db).apply(args.cycle_id, args.change)
    finally:
        await db.dispose()
    print_cycle(cycle)
    return EXIT_OK


def _runner(db: Any, concurrency: int) -> Any:
    from agentforge.benchmarks import BenchmarkRunner
    from agentforge.settings import get_settings
    from agentforge.storage.tracking import StorageRecorder

    return BenchmarkRunner(get_settings(), recorder=StorageRecorder(db), concurrency=concurrency)


async def cmd_evaluate(args: argparse.Namespace) -> int:
    from agentforge.improvement.cycle import CycleStatus
    from agentforge.improvement.loop import ImprovementLoop

    db = await _open()
    try:
        cycle = await ImprovementLoop(db).evaluate(args.cycle_id, _runner(db, args.concurrency))
    finally:
        await db.dispose()
    if args.json:
        _dump(cycle)
    else:
        print_cycle(cycle)
    return EXIT_OK if cycle.status == CycleStatus.EVALUATED else EXIT_FAILED


async def cmd_reject(args: argparse.Namespace) -> int:
    from agentforge.improvement.loop import ImprovementLoop

    db = await _open()
    try:
        cycle = await ImprovementLoop(db).reject(args.cycle_id, args.reason)
    finally:
        await db.dispose()
    print_cycle(cycle)
    return EXIT_OK


async def run_cycles(
    db: Any, benchmark_run_id: str, *, cycles: int, runner: Any
) -> list[ImprovementCycle]:
    """Run up to ``cycles`` full improvement cycles starting from a baseline benchmark.

    Stops early when the proposal is empty, the evaluation fails, or the new
    version did not improve (a regression is reverted as a new version).
    """
    from agentforge.improvement.comparison import Verdict
    from agentforge.improvement.cycle import CycleStatus
    from agentforge.improvement.loop import ImprovementLoop

    loop = ImprovementLoop(db)
    done: list[ImprovementCycle] = []
    baseline = benchmark_run_id
    for _ in range(max(1, cycles)):
        cycle = await loop.propose(baseline)
        if not cycle.proposal.changes:
            done.append(cycle)
            break
        cycle = await loop.apply(cycle.id)
        cycle = await loop.evaluate(cycle.id, runner)
        comparison = cycle.comparison
        if cycle.status != CycleStatus.EVALUATED or comparison is None:
            done.append(cycle)
            break
        if comparison.verdict == Verdict.REGRESSED:
            done.append(await loop.reject(cycle.id, "regressed against the baseline"))
            break
        done.append(cycle)
        if comparison.candidate is not None and comparison.candidate.pass_rate >= 1.0:
            break
        assert cycle.candidate_benchmark_run_id is not None  # noqa: S101 - set by evaluate
        baseline = cycle.candidate_benchmark_run_id
    return done


async def cmd_run(args: argparse.Namespace) -> int:
    from agentforge.improvement.cycle import CycleStatus

    db = await _open()
    try:
        cycles = await run_cycles(
            db,
            args.benchmark_run_id,
            cycles=args.cycles,
            runner=_runner(db, args.concurrency),
        )
    finally:
        await db.dispose()
    if args.json:
        print(json.dumps([c.model_dump(mode="json") for c in cycles], indent=2, default=str))
    else:
        for cycle in cycles:
            print_cycle(cycle)
            print()
    return EXIT_OK if cycles and cycles[-1].status != CycleStatus.FAILED else EXIT_FAILED


async def cmd_history(args: argparse.Namespace) -> int:
    from agentforge.improvement.loop import ImprovementLoop

    db = await _open()
    try:
        loop = ImprovementLoop(db)
        agent = await loop.agents.resolve(args.agent)
        versions = await loop.agents.versions(agent.id)
        benches = await loop.benchmarks.list(agent_id=agent.id, limit=200)
        cycles = await loop.cycles.list(agent_id=agent.id)
    finally:
        await db.dispose()
    if args.json:
        print(
            json.dumps(
                {
                    "agent": {"id": agent.id, "name": agent.name, "version": agent.version},
                    "versions": [v.model_dump(mode="json") for v in versions],
                    "benchmarks": [
                        b.model_dump(mode="json", exclude={"suite", "agent_config", "results"})
                        for b in benches
                    ],
                    "improvements": [c.model_dump(mode="json") for c in cycles],
                },
                indent=2,
                default=str,
            )
        )
        return EXIT_OK
    print(f"agent {agent.name} ({agent.id}) current v{agent.version}")
    print("versions:")
    for v in versions:
        summary = v.change_summary.replace("\n", " ")[:100]
        print(f"  v{v.version:<3} {v.created_at:%Y-%m-%d %H:%M}  {v.source.value:<11} {summary}")
    print("benchmarks:")
    for b in benches:
        rate = _pct(b.summary.pass_rate) if b.summary else "-"
        version = f"v{b.agent_version}" if b.agent_version is not None else "-"
        print(
            f"  {b.id}  {b.created_at:%Y-%m-%d %H:%M}  {version:<4} {b.suite_id}@{b.suite.version}"
            f"  {b.result_class.value:<7} {b.status.value:<9} pass {rate}"
        )
    print("improvements:")
    for c in cycles:
        verdict = c.comparison.verdict.value if c.comparison else "-"
        target = f"v{c.to_version}" if c.to_version is not None else "-"
        print(
            f"  {c.id}  {c.created_at:%Y-%m-%d %H:%M}  v{c.from_version} -> {target:<4}"
            f" {c.status.value:<10} {verdict}"
        )
    return EXIT_OK


__all__ = ["print_analysis", "print_comparison", "print_cycle", "register", "run_cycles"]
