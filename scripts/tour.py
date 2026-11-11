#!/usr/bin/env python3
"""A five-minute, fully offline tour of the AgentForge loop (see docs/tour.md).

    uv run python scripts/tour.py              # fresh temporary data directory
    uv run python scripts/tour.py --keep DIR   # keep the database in DIR (for the dashboard)

Runs the documented CLI commands in order — benchmark a versioned agent, read
the failure analysis, let the rule-based proposer create version 2, re-run the
same suite snapshot, compare, and gate both directions — and checks each exit
code. Uses only the scripted provider: no API key, no model calls, no network.
Its results are OFFLINE replays; they demonstrate the pipeline, never a model.

Exit status: 0 when every step behaved as documented, 1 otherwise.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shlex
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = "dogfood/benchmarks/coding.yaml"
DEMO_AGENT = "dogfood/agents/offline/demo-coder-v1.yaml"  # max_steps 3: fails 0/2
REFERENCE_AGENT = "dogfood/agents/offline/coding.yaml"  # reference solutions: passes 2/2
BASELINE = "examples/ci/baselines/dogfood-coding-offline.json"  # committed CI baseline
AGENT_NAME = "dogfood-demo-coder"


@dataclass
class Step:
    title: str
    why: str
    argv: list[str]
    expect_exit: int = 0
    show_output: bool = True


@dataclass
class Outcome:
    step: Step
    exit_code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.exit_code == self.step.expect_exit


def run_cli(argv: Sequence[str]) -> tuple[int, str]:
    """Run ``agentforge ARGV`` in-process and capture stdout + stderr."""
    from agentforge.cli import main
    from agentforge.settings import get_settings

    get_settings.cache_clear()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        try:
            code = main(list(argv))
        except SystemExit as exc:  # argparse errors
            code = exc.code if isinstance(exc.code, int) else 2
    return code, buffer.getvalue()


def command_line(argv: Sequence[str]) -> str:
    return "agentforge " + shlex.join(argv)


class Tour:
    def __init__(self, out: Callable[[str], None] = print) -> None:
        self.out = out
        self.outcomes: list[Outcome] = []

    def step(self, step: Step) -> Outcome:
        number = len(self.outcomes) + 1
        self.out(f"\n## {number}. {step.title}\n")
        self.out(step.why)
        self.out(f"\n$ {command_line(step.argv)}")
        code, output = run_cli(step.argv)
        outcome = Outcome(step, code, output)
        self.outcomes.append(outcome)
        if step.show_output and output.strip():
            self.out(output.rstrip())
        marker = "ok" if outcome.ok else "UNEXPECTED"
        self.out(f"[exit {code}, expected {step.expect_exit}: {marker}]")
        return outcome

    def bench_id(self, outcome: Outcome) -> str:
        """The benchmark id from ``bench run --json`` output (after any agent line)."""
        text = outcome.output
        start = text.find("{")
        if not outcome.ok or start < 0:
            raise RuntimeError(f"benchmark step failed:\n{text}")
        bench_id: str = json.loads(text[start:])["id"]
        return bench_id

    def run(self) -> bool:
        base = self.step(
            Step(
                "Benchmark a versioned agent",
                "`--save-agent` stores the config as an immutable agent version (v1) and\n"
                "links the benchmark to it. The demo agent's step budget (3) is too small\n"
                "for the suite, so both tasks fail.",
                ["bench", "run", SUITE, "-a", DEMO_AGENT, "--save-agent", "--json"],
                show_output=False,
            )
        )
        v1 = self.bench_id(base)
        self.out(f"(benchmark id {v1}; full JSON report omitted)")

        self.step(
            Step(
                "Analyse the failures",
                "Every failed run is classified from its record, with evidence.",
                ["improve", "analyze", v1],
            )
        )
        cycle = self.step(
            Step(
                "Propose, apply and re-evaluate (one improvement cycle)",
                "The rule-based proposer changes only allowlisted config paths. The\n"
                "change is applied as version 2, benchmarked on v1's exact suite\n"
                "snapshot, and compared with Wilson 95% intervals.",
                ["improve", "run", v1, "--cycles", "1"],
            )
        )
        history = self.step(
            Step(
                "Inspect the agent's history",
                "Versions, benchmarks and cycles are all persisted; nothing is overwritten.",
                ["improve", "history", AGENT_NAME],
            )
        )
        if not (cycle.ok and history.ok):
            return False
        code, text = run_cli(["improve", "history", AGENT_NAME, "--json"])
        if code != 0:
            raise RuntimeError(f"history --json failed:\n{text}")
        benchmarks = json.loads(text)["benchmarks"]
        v2 = next(b["id"] for b in benchmarks if b["agent_version"] == 2)

        self.step(
            Step(
                "Gate the change: v1 -> v2",
                "The CI regression gate exits 0 when nothing regressed.",
                ["bench", "gate", "--baseline", v1, "--candidate", v2],
                expect_exit=0,
            )
        )
        self.step(
            Step(
                "Gate a regression: v2 -> v1",
                "Swapping the roles shows what a regressing change looks like: exit 1.",
                ["bench", "gate", "--baseline", v2, "--candidate", v1],
                expect_exit=1,
            )
        )
        self.step(
            Step(
                "Gate against the committed CI baseline",
                "In CI the baseline is a committed report file. v1 regresses against it.",
                ["bench", "gate", "--baseline", BASELINE, "--candidate", v1],
                expect_exit=1,
            )
        )
        return all(o.ok for o in self.outcomes)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--keep", metavar="DIR", help="data directory to use and keep (default: a temporary one)"
    )
    args = parser.parse_args(argv)
    keep = Path(args.keep).resolve() if args.keep else None  # relative to the caller's cwd

    os.chdir(ROOT)  # the documented commands use repository-relative paths
    os.environ.pop("AGENTFORGE_DATABASE_URL", None)
    with contextlib.ExitStack() as stack:
        if keep is not None:
            data_dir = keep
            data_dir.mkdir(parents=True, exist_ok=True)
        else:
            data_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="af-tour-")))
        os.environ["AGENTFORGE_DATA_DIR"] = str(data_dir)
        print("# AgentForge tour (OFFLINE: scripted provider, no model calls)")
        print(f"data directory: {data_dir if args.keep else '(temporary)'}")
        tour = Tour()
        try:
            ok = tour.run()
        except RuntimeError as exc:
            print(f"\ntour stopped: {exc}")
            ok = False
        print("\n" + ("tour complete: every step behaved as documented" if ok else "tour FAILED"))
        if ok and args.keep:
            print(
                f"\nBrowse the results: AGENTFORGE_DATA_DIR={data_dir} uv run agentforge serve\n"
                "then `cd web && npm run dev` and open http://localhost:3000/improvement"
            )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
