#!/usr/bin/env python3
"""Run the AgentForge dogfooding program (see dogfood/README.md).

    python scripts/dogfood.py offline            # scripted reference agents + improvement demo
    python scripts/dogfood.py real --provider anthropic --model claude-sonnet-5

OFFLINE and REAL results are written to separate directories
(``dogfood/results/offline`` and ``dogfood/results/real``) and never mixed.
``real`` refuses to run without the provider's credentials and writes nothing.
Every run is also stored in the AgentForge database, so the dashboard's
Improvement page shows the same history.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOGFOOD = ROOT / "dogfood"


@dataclass(frozen=True)
class Role:
    name: str
    suite: str
    agent: str  # real-model config
    offline_agent: str  # scripted reference solutions


ROLES = [
    Role("coding", "coding.yaml", "coding.yaml", "coding.yaml"),
    Role("debugging", "debugging.yaml", "debugging.yaml", "debugging.yaml"),
    Role("data-analysis", "data-analysis.yaml", "data-analysis.yaml", "data-analysis.yaml"),
    Role("security-analysis", "security.yaml", "security-analysis.yaml", "security-analysis.yaml"),
    Role(
        "github-issue-solver",
        "issues.yaml",
        "github-issue-solver.yaml",
        "github-issue-solver.yaml",
    ),
    Role("engineer", "hard.yaml", "engineer.yaml", "engineer.yaml"),
]
DEMO_AGENT = DOGFOOD / "agents" / "offline" / "demo-coder-v1.yaml"
DEMO_SUITE = DOGFOOD / "benchmarks" / "coding.yaml"
SANDBOX_IMAGE = "agentforge-sandbox:latest"


def _display(path: Path) -> Path:
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def _select(names: list[str] | None) -> list[Role]:
    if not names:
        return ROLES
    known = {r.name: r for r in ROLES}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise SystemExit(f"unknown role(s): {', '.join(unknown)} (known: {', '.join(known)})")
    return [known[n] for n in names]


class Program:
    def __init__(self, database_url: str | None, results: Path, save: bool) -> None:
        from agentforge.settings import get_settings

        self.settings = get_settings()
        if database_url:
            self.settings = self.settings.model_copy(update={"database_url": database_url})
        self.results = results
        self.save = save
        self.db: Any = None
        self.saved: list[Path] = []

    async def __aenter__(self) -> Program:
        from agentforge.storage import Database

        self.db = Database(self.settings.resolved_database_url)
        await self.db.migrate()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.db.dispose()

    def runner(self, concurrency: int = 1) -> Any:
        from agentforge.benchmarks import BenchmarkRunner
        from agentforge.storage.tracking import StorageRecorder

        return BenchmarkRunner(
            self.settings, recorder=StorageRecorder(self.db), concurrency=concurrency
        )

    async def benchmark(self, config: Any, suite_path: Path, repeats: int | None) -> Any:
        from agentforge.benchmarks import load_suite
        from agentforge.storage import AgentRepository

        agent = await AgentRepository(self.db).register(config)
        bench = await self.runner().run(
            load_suite(suite_path),
            config,
            repeats=repeats,
            agent_id=agent.id,
            agent_version=agent.version,
        )
        await self.record(bench.id)
        return bench

    async def record(self, bench_id: str) -> Any:
        from agentforge.benchmarks.report import build_report, save_report
        from agentforge.storage import RunRepository
        from agentforge.storage.tracking import BenchmarkRepository

        bench = await BenchmarkRepository(self.db).get(bench_id)
        page = await RunRepository(self.db).list(
            benchmark_run_id=bench.id, limit=len(bench.results) + 50
        )
        report = build_report(bench, {run.id: run for run in page.items})
        s = report.summary
        tokens = (
            "n/a"
            if s.total_input_tokens is None
            else f"{s.total_input_tokens}/{s.total_output_tokens}"
        )
        print(
            f"  [{report.result_class.value.upper()}] {report.suite_id}@{report.suite_version}"
            f"  {report.agent_name} v{report.agent_version}  {report.provider}/{report.model}"
            f"  pass {s.passed}/{s.runs}  tokens {tokens}"
            f"  est. cost {'n/a' if s.estimated_cost_usd is None else s.estimated_cost_usd}"
            f"  ({report.benchmark_run_id})"
        )
        if self.save:
            path = save_report(self.results, report)
            self.saved.append(path)
            print(f"    report: {_display(path)}")
        return report


# ------------------------------------------------------------------ offline
async def offline(args: argparse.Namespace) -> int:
    from agentforge.config_files import load_agent_config
    from agentforge.improvement.cli import print_cycle, run_cycles

    async with Program(args.database_url, Path(args.results), not args.no_save) as program:
        print("OFFLINE / SCRIPTED PROVIDER — validates the benchmark and pipeline, not a model")
        failures = 0
        for role in _select(args.roles):
            config = load_agent_config(DOGFOOD / "agents" / "offline" / role.offline_agent)
            bench = await program.benchmark(
                config, DOGFOOD / "benchmarks" / role.suite, args.repeats
            )
            failures += bench.summary.runs - bench.summary.passed if bench.summary else 1
        if not args.skip_demo:
            print("\nImprovement-loop demo (offline; demonstrates the loop mechanics only)")
            config = load_agent_config(DEMO_AGENT)
            baseline = await program.benchmark(config, DEMO_SUITE, 3)
            cycles = await run_cycles(program.db, baseline.id, cycles=2, runner=program.runner())
            for cycle in cycles:
                print_cycle(cycle)
                if cycle.candidate_benchmark_run_id:
                    await program.record(cycle.candidate_benchmark_run_id)
                if program.save:
                    folder = program.results / "offline" / "improvement-demo"
                    folder.mkdir(parents=True, exist_ok=True)
                    stamp = cycle.created_at.strftime("%Y%m%dT%H%M%SZ")
                    path = folder / f"{stamp}-{cycle.agent_name}-{cycle.id}.json"
                    path.write_text(
                        json.dumps(cycle.model_dump(mode="json"), indent=2) + "\n",
                        encoding="utf-8",
                    )
                    print(f"    cycle: {_display(path)}")
        if failures:
            print(f"\n{failures} reference run(s) failed: a benchmark task or check is broken.")
            return 1
        return 0


# --------------------------------------------------------------------- real
def _credentials_problem(provider: str, base_url: str | None) -> str | None:
    from agentforge.llm.registry import available_providers

    info = {p.name: p for p in available_providers()}.get(provider)
    if info is None:
        return f"unknown provider '{provider}'"
    if provider == "scripted":
        return "the scripted provider is offline; use `offline` instead"
    if provider == "local":
        return None if base_url else "the local provider needs --base-url"
    if info.api_key_env and not os.environ.get(info.api_key_env):
        # Name only the provider: nothing derived from credential settings is printed.
        return (
            f"no credentials for provider '{provider}' "
            "(see `agentforge providers` for the environment variable)"
        )
    return None


def _sandbox_problem() -> str | None:
    if shutil.which("docker") is None:
        return "docker is not installed"
    probe = subprocess.run(  # noqa: S603 - fixed argv
        ["docker", "image", "inspect", SANDBOX_IMAGE],  # noqa: S607
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        return (
            f"the sandbox image {SANDBOX_IMAGE} is missing (docker build -f "
            "docker/sandbox.Dockerfile -t agentforge-sandbox:latest .)"
        )
    return None


def real_config(
    path: Path, *, provider: str, model: str | None, base_url: str | None, sandbox: str
) -> Any:
    """A dogfood agent config with the provider/model/sandbox overrides applied (validated)."""
    from agentforge.config_files import load_agent_config
    from agentforge.core.config import AgentConfig

    data = load_agent_config(path).model_dump(mode="json")
    data["model"].update(
        {"provider": provider, "model": model or data["model"]["model"], "base_url": base_url}
    )
    data["sandbox"]["kind"] = sandbox
    return AgentConfig.model_validate(data)


async def real(args: argparse.Namespace) -> int:
    from agentforge.improvement.cli import print_cycle, run_cycles

    problem = _credentials_problem(args.provider, args.base_url)
    if problem:
        print(f"REAL MODEL PROVIDER: not run — {problem}. No real-model results were produced.")
        return 0
    if args.sandbox == "docker" and (problem := _sandbox_problem()):
        print(
            f"REAL MODEL PROVIDER: not run — {problem}. "
            "Use --sandbox local only on a trusted machine."
        )
        return 2

    async with Program(args.database_url, Path(args.results), not args.no_save) as program:
        print(f"REAL MODEL PROVIDER — {args.provider}/{args.model or '(default model)'}")
        for role in _select(args.roles):
            config = real_config(
                DOGFOOD / "agents" / role.agent,
                provider=args.provider,
                model=args.model,
                base_url=args.base_url,
                sandbox=args.sandbox,
            )
            bench = await program.benchmark(
                config, DOGFOOD / "benchmarks" / role.suite, args.repeats
            )
            if args.improve_cycles:
                cycles = await run_cycles(
                    program.db, bench.id, cycles=args.improve_cycles, runner=program.runner()
                )
                for cycle in cycles:
                    print_cycle(cycle)
                    if cycle.candidate_benchmark_run_id:
                        await program.record(cycle.candidate_benchmark_run_id)
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database-url", help="default: the AgentForge settings database")
    parser.add_argument("--results", default=str(DOGFOOD / "results"))
    parser.add_argument("--no-save", action="store_true", help="do not write report files")
    parser.add_argument(
        "--roles",
        type=lambda value: [v.strip() for v in value.split(",") if v.strip()],
        metavar="ROLE[,ROLE...]",
        help="default: all (" + ", ".join(r.name for r in ROLES) + ")",
    )
    parser.add_argument("-r", "--repeats", type=int)
    sub = parser.add_subparsers(dest="mode", required=True)
    off = sub.add_parser("offline", help="scripted reference agents + improvement-loop demo")
    off.add_argument("--skip-demo", action="store_true")
    off.set_defaults(handler=offline)
    rl = sub.add_parser("real", help="real model provider (requires credentials)")
    rl.add_argument("--provider", default="anthropic")
    rl.add_argument("--model", help="default: the model in each dogfood agent config")
    rl.add_argument("--base-url", help="for OpenAI-compatible local servers")
    rl.add_argument("--sandbox", choices=["docker", "local"], default="docker")
    rl.add_argument("--improve-cycles", type=int, default=0)
    rl.set_defaults(handler=real)
    args = parser.parse_args(argv)
    return asyncio.run(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
