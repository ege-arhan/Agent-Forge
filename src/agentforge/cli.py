"""``agentforge`` command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from agentforge import __version__
from agentforge.core.errors import AgentForgeError
from agentforge.core.models import Run, RunStatus

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


# --------------------------------------------------------------------- output
class ConsoleObserver:
    """Prints a compact live trace of a run."""

    def __init__(self, stream: Any = None) -> None:
        self.stream = stream or sys.stderr

    def _print(self, text: str) -> None:
        print(text, file=self.stream, flush=True)

    async def on_event(self, event: Any, run: Run) -> None:
        data = event.data
        if event.type == "run.started":
            self._print(
                f"▶ run {run.id}  agent={run.agent_name}  model={run.config.model.provider}"
                f"/{run.config.model.model or '-'}"
            )
            self._print(f"  workspace: {run.workspace}")
        elif event.type == "plan.created" and run.plan:
            self._print("  plan:")
            for i, item in enumerate(run.plan, 1):
                self._print(f"    {i}. {item}")
        elif event.type == "llm.retry":
            self._print(f"  ↻ LLM retry {data.get('attempt')} after error: {data.get('error')}")
        elif event.type == "step.finished":
            step = run.steps[data["step"]]
            if step.thought:
                first = step.thought.strip().splitlines()[0][:160] if step.thought.strip() else ""
                if first:
                    self._print(f"  [{step.index}] {first}")
            for call in step.tool_calls:
                args = json.dumps(call.arguments)[:100]
                self._print(f"      → {call.tool}({args}) {call.status.value} {call.duration_ms}ms")
        elif event.type == "evaluation.finished":
            mark = "✔" if data.get("passed") else "✘"
            self._print(f"  {mark} evaluation score={data.get('score')}")
        elif event.type == "run.finished":
            self._print(f"■ {run.status.value}" + (f": {run.error.message}" if run.error else ""))


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def _run_summary(run: Run) -> str:
    m = run.metrics
    lines = [
        f"run:        {run.id}",
        f"status:     {run.status.value}",
        f"duration:   {m.duration_seconds}s   steps: {m.steps}   tool calls: {m.tool_calls}"
        f" (success rate {m.tool_success_rate if m.tool_success_rate is not None else '-'})",
        f"tokens:     in={m.input_tokens} out={m.output_tokens}   cost: "
        + (f"${m.cost_usd:.4f}" if m.cost_usd is not None else "unknown"),
    ]
    if run.evaluation:
        lines.append(
            f"evaluation: {'PASSED' if run.evaluation.passed else 'FAILED'}"
            f" score={run.evaluation.score}"
        )
        for result in run.evaluation.results:
            mark = "✔" if result.passed else "✘"
            detail = f" - {result.details.splitlines()[0]}" if result.details else ""
            lines.append(f"  {mark} {result.name}{detail}")
    if run.error:
        lines.append(f"error:      {run.error.type}: {run.error.message}")
    if run.result:
        lines.append("result:\n" + run.result)
    return "\n".join(lines)


# ------------------------------------------------------------------- helpers
def _load_evaluators(values: list[str] | None) -> list[Any]:
    from agentforge.evaluation.base import EvaluatorSpec

    specs: list[EvaluatorSpec] = []
    for value in values or []:
        path = Path(value)
        raw: Any
        if path.is_file():
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        else:
            raw = json.loads(value)
        items = raw if isinstance(raw, list) else [raw]
        specs.extend(EvaluatorSpec.model_validate(item) for item in items)
    return specs


async def _open_db(settings: Any) -> Any:
    from agentforge.storage import Database

    db = Database(settings.resolved_database_url)
    await db.migrate()
    return db


# ------------------------------------------------------------------ commands
async def cmd_run(args: argparse.Namespace) -> int:
    from agentforge.config_files import load_agent_config
    from agentforge.runtime.factory import prepare_run
    from agentforge.settings import get_settings
    from agentforge.storage import (
        AgentRepository,
        PersistenceObserver,
        RunRepository,
        SqlMemoryStore,
    )

    settings = get_settings()
    config = load_agent_config(args.agent)
    evaluators = _load_evaluators(args.eval)
    observers: list[Any] = [] if args.quiet else [ConsoleObserver()]
    if settings.otel_enabled:
        from agentforge.observability.otel import configure_tracing

        observers.append(configure_tracing())
    db = None
    memory = None
    agent_id = None
    if not args.no_db:
        db = await _open_db(settings)
        observers.append(PersistenceObserver(RunRepository(db)))
        memory = SqlMemoryStore(db)
        agent = await AgentRepository(db).get_by_name(config.name)
        agent_id = agent.id if agent else None
    try:
        prepared = prepare_run(
            config,
            args.goal,
            agent_id=agent_id,
            settings=settings,
            memory=memory,
            observers=observers,
            workspace_dir=args.workspace,
        )
        run = await prepared.execute(evaluators)
    finally:
        if db is not None:
            await db.dispose()
        if settings.otel_enabled:
            from opentelemetry import trace

            flush = getattr(trace.get_tracer_provider(), "force_flush", None)
            if flush is not None:
                flush()
    if args.json:
        _print_json(run.model_dump(mode="json"))
    else:
        print(_run_summary(run))
    ok = run.status == RunStatus.SUCCEEDED and (run.evaluation is None or run.evaluation.passed)
    return EXIT_OK if ok else EXIT_FAILED


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from agentforge.api.app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    return EXIT_OK


async def cmd_bench_run(args: argparse.Namespace) -> int:
    from agentforge.benchmarks import BenchmarkRunner, load_suite
    from agentforge.config_files import load_agent_config
    from agentforge.settings import get_settings
    from agentforge.storage.tracking import StorageRecorder

    settings = get_settings()
    suite = load_suite(args.suite)
    config = load_agent_config(args.agent)
    if args.no_db and (args.save_agent or args.report):
        print("error: --save-agent and --report need the database", file=sys.stderr)
        return EXIT_USAGE
    db = None if args.no_db else await _open_db(settings)
    recorder = StorageRecorder(db) if db is not None else None
    try:
        agent = None
        if db is not None and args.save_agent:
            from agentforge.storage import AgentRepository

            agent = await AgentRepository(db).register(config)
            print(f"agent {agent.name} v{agent.version} ({agent.id})", file=sys.stderr)
        bench = await BenchmarkRunner(
            settings, recorder=recorder, concurrency=args.concurrency
        ).run(
            suite,
            config,
            repeats=args.repeats,
            task_ids=args.task or None,
            agent_id=agent.id if agent else None,
            agent_version=agent.version if agent else None,
        )
        if db is not None and args.report:
            path = await _save_report(db, bench.id, Path(args.report))
            print(f"report: {path}", file=sys.stderr)
    finally:
        if db is not None:
            await db.dispose()
    if args.json:
        _print_json(bench.model_dump(mode="json", exclude={"suite", "agent_config"}))
        return EXIT_OK
    s = bench.summary
    print(
        f"benchmark {bench.id}  suite={suite.id}  agent={config.name}  status={bench.status.value}"
        f"  results={bench.result_class.value.upper()}"
    )
    header = ("task", "repeat", "status", "pass", "score", "steps", "time")
    print("{:<28} {:>6} {:<10} {:<5} {:>6} {:>5} {:>7}".format(*header))
    for r in bench.results:
        duration = f"{r.duration_seconds:.1f}s" if r.duration_seconds is not None else "-"
        print(
            f"{r.task_id:<28} {r.repeat:>6} {r.status.value:<10} {'yes' if r.passed else 'no':<5}"
            f" {r.score:>6.2f} {r.steps:>5} {duration:>7}"
        )
    if s:
        ci = (
            f" (95% CI {s.pass_rate_ci95[0]:.2f}-{s.pass_rate_ci95[1]:.2f})"
            if s.pass_rate_ci95
            else ""
        )
        cost = f"${s.total_cost_usd:.4f}" if s.total_cost_usd is not None else "unknown"
        print(
            f"\npass rate {s.pass_rate:.2%}{ci}  mean score {s.mean_score:.3f}  runs {s.runs}"
            f"  tokens in/out {s.total_input_tokens}/{s.total_output_tokens}  cost {cost}"
        )
    return EXIT_OK if bench.status == RunStatus.SUCCEEDED else EXIT_FAILED


async def _report(db: Any, bench_id: str) -> Any:
    from agentforge.benchmarks.report import build_report
    from agentforge.storage import RunRepository
    from agentforge.storage.tracking import BenchmarkRepository

    bench = await BenchmarkRepository(db).get(bench_id)
    page = await RunRepository(db).list(benchmark_run_id=bench.id, limit=len(bench.results) + 50)
    return build_report(bench, {run.id: run for run in page.items})


async def _save_report(db: Any, bench_id: str, root: Path) -> Path:
    from agentforge.benchmarks.report import save_report

    return save_report(root, await _report(db, bench_id))


async def cmd_bench_report(args: argparse.Namespace) -> int:
    from agentforge.benchmarks.report import render_markdown, save_report
    from agentforge.settings import get_settings

    db = await _open_db(get_settings())
    try:
        report = await _report(db, args.benchmark_run_id)
    finally:
        await db.dispose()
    if args.out:
        print(save_report(Path(args.out), report))
    elif args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(render_markdown(report))
    return EXIT_OK


async def cmd_bench_compare(args: argparse.Namespace) -> int:
    from agentforge.improvement.loop import ImprovementLoop
    from agentforge.settings import get_settings

    db = await _open_db(get_settings())
    try:
        comparison = await ImprovementLoop(db).compare(args.baseline, args.candidate)
    finally:
        await db.dispose()
    if args.json:
        print(comparison.model_dump_json(indent=2))
    else:
        from agentforge.improvement.cli import print_comparison

        print_comparison(comparison)
    return EXIT_OK if comparison.comparable else EXIT_FAILED


def cmd_bench_list(args: argparse.Namespace) -> int:
    from agentforge.benchmarks import discover_suites
    from agentforge.settings import get_settings

    directory = args.dir or get_settings().benchmark_dirs
    for suite_id, (path, suite) in discover_suites(directory).items():
        print(f"{suite_id:<24} {len(suite.tasks):>3} tasks  {path}  {suite.name}")
    return EXIT_OK


async def cmd_experiment_run(args: argparse.Namespace) -> int:
    from agentforge.benchmarks import BenchmarkRunner
    from agentforge.experiments import ExperimentRunner, compare, load_experiment
    from agentforge.settings import get_settings
    from agentforge.storage.tracking import StorageRecorder

    settings = get_settings()
    spec, suite, base = load_experiment(args.spec)
    db = None if args.no_db else await _open_db(settings)
    recorder = StorageRecorder(db) if db is not None else None
    try:
        experiment = await ExperimentRunner(
            BenchmarkRunner(settings, recorder=recorder, concurrency=args.concurrency), recorder
        ).run(spec, suite, base)
    finally:
        if db is not None:
            await db.dispose()
    rows = compare(experiment)
    if args.json:
        _print_json(
            {
                "experiment": experiment.model_dump(mode="json"),
                "comparison": [r.model_dump(mode="json") for r in rows],
            }
        )
        return EXIT_OK
    print(f"experiment {experiment.id}  {experiment.name}  suite={suite.id}")
    print(
        f"{'variant':<24} {'runs':>4} {'pass rate':>9} {'95% CI':>13} {'Δ vs base':>9} "
        f"{'score':>6} {'steps':>6} {'cost':>9}"
    )
    for r in rows:
        ci = f"{r.pass_rate_ci95[0]:.2f}-{r.pass_rate_ci95[1]:.2f}" if r.pass_rate_ci95 else "-"
        delta = f"{r.pass_rate_delta:+.2f}" if r.pass_rate_delta is not None else "-"
        cost = f"${r.total_cost_usd:.4f}" if r.total_cost_usd is not None else "unknown"
        steps = f"{r.mean_steps:.1f}" if r.mean_steps is not None else "-"
        print(
            f"{r.variant:<24} {r.runs:>4} {r.pass_rate:>9.2%} {ci:>13} {delta:>9} "
            f"{r.mean_score:>6.3f} {steps:>6} {cost:>9}"
        )
    print("\nNote: results describe these configurations on this suite only.")
    return EXIT_OK


async def cmd_runs_list(args: argparse.Namespace) -> int:
    from agentforge.settings import get_settings
    from agentforge.storage import RunRepository

    db = await _open_db(get_settings())
    try:
        status = RunStatus(args.status) if args.status else None
        page = await RunRepository(db).list(status=status, limit=args.limit)
    finally:
        await db.dispose()
    for run in page.items:
        passed = "-" if run.evaluation is None else ("pass" if run.evaluation.passed else "fail")
        print(
            f"{run.id}  {run.created_at:%Y-%m-%d %H:%M}  {run.status.value:<10} {passed:<5}"
            f" {run.agent_name:<20} {run.goal[:60]!r}"
        )
    print(f"({len(page.items)} of {page.total})")
    return EXIT_OK


async def cmd_runs_show(args: argparse.Namespace) -> int:
    from agentforge.settings import get_settings
    from agentforge.storage import RunRepository

    db = await _open_db(get_settings())
    try:
        run = await RunRepository(db).get(args.run_id)
    finally:
        await db.dispose()
    if args.json:
        _print_json(run.model_dump(mode="json"))
    else:
        print(_run_summary(run))
    return EXIT_OK


async def cmd_agents_create(args: argparse.Namespace) -> int:
    from agentforge.config_files import load_agent_config
    from agentforge.settings import get_settings
    from agentforge.storage import AgentRepository

    config = load_agent_config(args.file)
    db = await _open_db(get_settings())
    try:
        agent = await AgentRepository(db).register(config)
    finally:
        await db.dispose()
    print(f"{agent.id}  {agent.name}  v{agent.version}")
    return EXIT_OK


async def cmd_agents_list(args: argparse.Namespace) -> int:
    from agentforge.settings import get_settings
    from agentforge.storage import AgentRepository

    db = await _open_db(get_settings())
    try:
        agents = await AgentRepository(db).list()
    finally:
        await db.dispose()
    for agent in agents:
        m = agent.config.model
        print(f"{agent.id}  {agent.name:<24} v{agent.version}  {m.provider}/{m.model or '-'}")
    return EXIT_OK


def cmd_tools(args: argparse.Namespace) -> int:
    from agentforge.tools.registry import default_registry

    for info in default_registry().describe():
        perms = ",".join(info.permissions) or "-"
        print(f"{info.name:<28} {info.toolset or '-':<11} {perms:<24} {info.description}")
    return EXIT_OK


def cmd_providers(args: argparse.Namespace) -> int:
    from agentforge.llm.registry import available_providers

    for p in available_providers():
        print(f"{p.name:<12} key={p.api_key_env or '-':<20} {p.description}")
    return EXIT_OK


async def cmd_db_upgrade(args: argparse.Namespace) -> int:
    from agentforge.settings import get_settings
    from agentforge.storage.migrate import current_revision

    settings = get_settings()
    db = await _open_db(settings)  # runs migrations
    try:
        revision = await current_revision(db)
    finally:
        await db.dispose()
    print(f"database at revision {revision}: {_safe_url(settings.resolved_database_url)}")
    return EXIT_OK


async def cmd_db_current(args: argparse.Namespace) -> int:
    from agentforge.settings import get_settings
    from agentforge.storage import Database
    from agentforge.storage.migrate import current_revision, head_revision

    settings = get_settings()
    db = Database(settings.resolved_database_url)
    try:
        revision = await current_revision(db)
    finally:
        await db.dispose()
    head = head_revision()
    state = "up to date" if revision == head else f"behind (head is {head})"
    print(f"current revision: {revision or 'none'} - {state}")
    return EXIT_OK


def _safe_url(url: str) -> str:
    """Hide credentials in database URLs."""
    import re

    return re.sub(r"//([^:/@]+):.*@", r"//\1:***@", url)


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentforge", description="Build, run, evaluate and benchmark LLM agents."
    )
    parser.add_argument("--version", action="version", version=f"agentforge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run an agent on a goal")
    run.add_argument("agent", help="agent config file (YAML/JSON)")
    run.add_argument("-g", "--goal", required=True)
    run.add_argument(
        "-e",
        "--eval",
        action="append",
        help="evaluator spec: JSON string or YAML/JSON file (repeatable)",
    )
    run.add_argument("-w", "--workspace", help="workspace directory (default: per-run dir)")
    run.add_argument("--json", action="store_true", help="print the full run record as JSON")
    run.add_argument("-q", "--quiet", action="store_true", help="no live trace")
    run.add_argument("--no-db", action="store_true", help="do not persist the run")
    run.set_defaults(handler=cmd_run)

    serve = sub.add_parser("serve", help="start the HTTP API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(handler=cmd_serve)

    bench = sub.add_parser("bench", help="benchmarks").add_subparsers(
        dest="bench_cmd", required=True
    )
    bench_run = bench.add_parser("run", help="run a benchmark suite")
    bench_run.add_argument("suite", help="suite file")
    bench_run.add_argument("-a", "--agent", required=True, help="agent config file")
    bench_run.add_argument("-r", "--repeats", type=int)
    bench_run.add_argument("-t", "--task", action="append", help="only this task id (repeatable)")
    bench_run.add_argument("-c", "--concurrency", type=int, default=1)
    bench_run.add_argument("--json", action="store_true")
    bench_run.add_argument("--no-db", action="store_true")
    bench_run.add_argument(
        "--save-agent",
        action="store_true",
        help="store the agent (new version if its config changed) and link the benchmark to it",
    )
    bench_run.add_argument(
        "--report", metavar="DIR", help="write a JSON+Markdown report under DIR/<offline|real>/"
    )
    bench_run.set_defaults(handler=cmd_bench_run)
    bench_report = bench.add_parser("report", help="result report of a stored benchmark run")
    bench_report.add_argument("benchmark_run_id")
    bench_report.add_argument("--out", metavar="DIR", help="save under DIR/<offline|real>/")
    bench_report.add_argument("--json", action="store_true")
    bench_report.set_defaults(handler=cmd_bench_report)
    bench_compare = bench.add_parser("compare", help="compare two runs of the same suite")
    bench_compare.add_argument("baseline")
    bench_compare.add_argument("candidate")
    bench_compare.add_argument("--json", action="store_true")
    bench_compare.set_defaults(handler=cmd_bench_compare)
    bench_list = bench.add_parser("list", help="list suites in a directory")
    bench_list.add_argument("dir", nargs="?")
    bench_list.set_defaults(handler=cmd_bench_list)

    exp = sub.add_parser("experiment", help="experiments").add_subparsers(
        dest="exp_cmd", required=True
    )
    exp_run = exp.add_parser("run", help="run an experiment spec")
    exp_run.add_argument("spec")
    exp_run.add_argument("-c", "--concurrency", type=int, default=1)
    exp_run.add_argument("--json", action="store_true")
    exp_run.add_argument("--no-db", action="store_true")
    exp_run.set_defaults(handler=cmd_experiment_run)

    runs = sub.add_parser("runs", help="inspect stored runs").add_subparsers(
        dest="runs_cmd", required=True
    )
    runs_list = runs.add_parser("list")
    runs_list.add_argument("--status", choices=[s.value for s in RunStatus])
    runs_list.add_argument("-n", "--limit", type=int, default=20)
    runs_list.set_defaults(handler=cmd_runs_list)
    runs_show = runs.add_parser("show")
    runs_show.add_argument("run_id")
    runs_show.add_argument("--json", action="store_true")
    runs_show.set_defaults(handler=cmd_runs_show)

    agents = sub.add_parser("agents", help="manage stored agents").add_subparsers(
        dest="agents_cmd", required=True
    )
    agents_create = agents.add_parser("create", help="create or update an agent from a file")
    agents_create.add_argument("file")
    agents_create.set_defaults(handler=cmd_agents_create)
    agents.add_parser("list").set_defaults(handler=cmd_agents_list)

    sub.add_parser("tools", help="list available tools").set_defaults(handler=cmd_tools)
    sub.add_parser("providers", help="list LLM providers").set_defaults(handler=cmd_providers)
    db = sub.add_parser("db", help="database").add_subparsers(dest="db_cmd", required=True)
    db.add_parser("upgrade", help="create or migrate the schema").set_defaults(
        handler=cmd_db_upgrade
    )
    db.add_parser("init", help="alias for upgrade").set_defaults(handler=cmd_db_upgrade)
    db.add_parser("current", help="show the schema revision").set_defaults(handler=cmd_db_current)

    from agentforge.improvement.cli import register as register_improve
    from agentforge.integrations.github.cli import register as register_github

    register_improve(sub)
    register_github(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    from agentforge.observability.logging import configure_logging
    from agentforge.settings import get_settings

    configure_logging("WARNING", json_format=get_settings().log_json)
    try:
        result = args.handler(args)
        if asyncio.iscoroutine(result):
            result = asyncio.run(result)
        return int(result)
    except AgentForgeError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
