#!/usr/bin/env python3
"""Limited real-model improvement experiment (see docs/REAL_MODEL_BENCHMARK.md).

One model (OpenCode Go ``deepseek-v4.1-flash``), two tasks of the hard dogfood
suite, one run each, through AgentForge's own improvement loop:

    agent v1 -> benchmark -> failure analysis -> proposal -> agent v2 -> benchmark -> comparison

Hard limits, enforced in code: at most 4 task executions in total (2 tasks x
v1/v2), sequential, no model-call retries (``retry.llm_max_attempts = 1``, no
evaluation retries), a fixed token budget per task. The proposal comes from
the built-in rule-based proposer, i.e. from v1's recorded failures; proposed
changes to the retry policy or the token budget are not applied. v2 is not
run when v1 passes every task (the tasks would then be too easy to show an
improvement), when authentication fails, or when nothing can be proposed.

Authentication: ``--auth env`` (``OPENCODE_API_KEY``) or ``--auth proxy`` (an
egress proxy injects the credential, e.g. Claude Cloud API Credentials; no key
in this process). Results are REAL-model results, stored under
``<results>/real/`` only; the full history (versions, benchmarks, analysis,
proposal, comparison) is kept in the AgentForge database in ``--data-dir``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import real_model_validation as rmv  # noqa: E402 - sibling script, shares metrics and scans

MODEL_NAME = "DeepSeek V4.1 Flash"
MODEL_ID = "deepseek-v4.1-flash"
SUITE_FILE = ROOT / "dogfood" / "benchmarks" / "hard.yaml"
AGENT_FILE = ROOT / "dogfood" / "agents" / "engineer.yaml"
AGENT_NAME = "dogfood-engineer-deepseek"
# The two hard tasks with the most ways to fail: a multi-file feature with six
# spec rules and hidden checks, and a two-cause bug whose regression tests are
# mutation-checked. Chosen before any real run; identical for v1 and v2.
TASKS = ["coupons-feature", "ledger-root-causes"]
MAX_EXECUTIONS = 4
DEFAULT_TOKEN_BUDGET = rmv.DEFAULT_TOKEN_BUDGET
SANDBOX_IMAGE = "python:3.12"  # python3 + git
# Proposed changes that are never applied in this experiment: retries would
# add model calls; the token budget is a fixed resource guard.
EXCLUDED_CHANGE_PATHS = ("retry.", "limits.max_total_tokens")


class BudgetExceededError(RuntimeError):
    pass


class ExecutionBudget:
    """Task executions left; a benchmark is only started if all its runs fit."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def reserve(self, executions: int) -> None:
        if self.used + executions > self.limit:
            raise BudgetExceededError(
                f"{executions} more task executions would exceed the limit of {self.limit} "
                f"({self.used} used)"
            )
        self.used += executions


def v1_config(*, base_url: str, auth: str, token_budget: int, sandbox: str) -> Any:
    """The engineer agent with the model swapped in; no retries, fixed budget."""
    from agentforge.config_files import load_agent_config
    from agentforge.core.config import AgentConfig

    data = load_agent_config(AGENT_FILE).model_dump(mode="json")
    data["name"] = AGENT_NAME
    data["model"].update(
        {
            "provider": rmv.PROVIDER,
            "model": MODEL_ID,
            "base_url": base_url,
            "api_key_env": rmv.KEY_ENV if auth == rmv.AUTH_ENV else None,
            "options": {
                **data["model"].get("options", {}),
                "auth": "api_key" if auth == rmv.AUTH_ENV else "proxy",
            },
        }
    )
    data["retry"]["llm_max_attempts"] = 1
    data["retry"]["evaluation_retries"] = 0
    data["limits"]["max_total_tokens"] = token_budget
    data["sandbox"].update({"kind": sandbox, "image": SANDBOX_IMAGE, "network": "none"})
    data["labels"] = {**data.get("labels", {}), "experiment": "limited-real-improvement"}
    return AgentConfig.model_validate(data)


def applicable_changes(proposal: Any) -> list[str]:
    return [c.id for c in proposal.changes if not c.path.startswith(EXCLUDED_CHANGE_PATHS)]


def stop_reason_after_v1(rows: list[rmv.Row]) -> str | None:
    """Why v2 must not run, or None to continue."""
    if any(r.auth_failed for r in rows):
        return "authentication failed (HTTP 401/403); no further model calls"
    if rows and all(r.task_success for r in rows):
        return (
            "v1 passed every task: the tasks were not difficult enough for this model to show "
            "an improvement, so no improvement was attempted"
        )
    return None


async def rows_for(db: Any, bench: Any, version: int) -> list[rmv.Row]:
    from agentforge.benchmarks.report import build_report
    from agentforge.storage import RunRepository

    page = await RunRepository(db).list(benchmark_run_id=bench.id, limit=len(bench.results) + 10)
    runs = {r.id: r for r in page.items}
    report = build_report(bench, runs)
    rows = []
    for record in report.runs:
        row = rmv.Row(
            model=f"{MODEL_NAME} · agent v{version}",
            model_id=MODEL_ID,
            phase=f"v{version}",
            suite=str(SUITE_FILE.relative_to(ROOT)),
            task=record.task_id,
            api_model=MODEL_ID,
        )
        rmv.fill_row(row, bench, runs.get(record.run_id), report, record)
        rows.append(row)
    return rows


async def save_reports(db: Any, results: Path, bench: Any) -> None:
    from agentforge.benchmarks.report import build_report, save_report
    from agentforge.storage import RunRepository

    page = await RunRepository(db).list(benchmark_run_id=bench.id, limit=len(bench.results) + 10)
    save_report(results, build_report(bench, {r.id: r for r in page.items}))


async def run_experiment(
    *,
    db: Any,
    settings: Any,
    config: Any,
    results: Path,
    budget: ExecutionBudget,
) -> dict[str, Any]:
    from agentforge.benchmarks import BenchmarkRunner, load_suite
    from agentforge.improvement.loop import ImprovementLoop
    from agentforge.storage import AgentRepository
    from agentforge.storage.tracking import BenchmarkRepository, StorageRecorder

    suite = load_suite(SUITE_FILE)
    missing = set(TASKS) - {t.id for t in suite.tasks}
    if missing:
        raise SystemExit(f"tasks not in {SUITE_FILE.name}: {sorted(missing)}")
    runner = BenchmarkRunner(settings, recorder=StorageRecorder(db), concurrency=1)
    agents = AgentRepository(db)
    agent = await agents.register(config, change_summary="baseline (v1)")
    out: dict[str, Any] = {"agent_id": agent.id, "v1_version": agent.version}

    budget.reserve(len(TASKS))
    print(f"v1: {MODEL_ID} on {', '.join(TASKS)}", flush=True)
    v1 = await runner.run(
        suite, config, repeats=1, task_ids=TASKS, agent_id=agent.id, agent_version=agent.version
    )
    await save_reports(db, results, v1)
    v1_rows = await rows_for(db, v1, agent.version)
    out.update(v1_benchmark_run_id=v1.id, v1_rows=v1_rows)
    for row in v1_rows:
        print(f"    v1 {row.task}: success={row.task_success} {row.failure_category or ''}")

    reason = stop_reason_after_v1(v1_rows)
    loop = ImprovementLoop(db)
    if reason is not None:
        out["analysis"] = (await loop.analyze(v1.id)).model_dump(mode="json")
        out["stopped"] = reason
        print(f"stopped: {reason}")
        return out

    cycle = await loop.propose(v1.id, notes="limited real improvement experiment")
    allowed = applicable_changes(cycle.proposal)
    skipped = [c.id for c in cycle.proposal.changes if c.id not in allowed]
    out.update(cycle_id=cycle.id, skipped_change_ids=skipped)
    if not allowed:
        cycle = await loop.reject(cycle.id, "no applicable change (retries/token budget excluded)")
        out["cycle"] = cycle.model_dump(mode="json")
        out["stopped"] = "the failure analysis produced no applicable configuration change"
        print(f"stopped: {out['stopped']}")
        return out
    cycle = await loop.apply(cycle.id, allowed)
    print(f"v2: applied {', '.join(allowed)} -> agent v{cycle.to_version}", flush=True)

    budget.reserve(len(cycle.task_ids) * cycle.repeats)
    cycle = await loop.evaluate(cycle.id, runner)
    out["cycle"] = cycle.model_dump(mode="json")
    if cycle.candidate_benchmark_run_id is None:
        out["stopped"] = f"evaluation did not run: {cycle.error}"
        return out
    v2 = await BenchmarkRepository(db).get(cycle.candidate_benchmark_run_id)
    await save_reports(db, results, v2)
    v2_rows = await rows_for(db, v2, cycle.to_version or agent.version + 1)
    out.update(v2_benchmark_run_id=v2.id, v2_rows=v2_rows)
    for row in v2_rows:
        print(f"    v2 {row.task}: success={row.task_success} {row.failure_category or ''}")
    verdict = cycle.comparison.verdict if cycle.comparison is not None else None
    print(f"comparison: {verdict}")
    return out


# ----------------------------------------------------------------- output
def _row_line(r: dict[str, Any]) -> str:
    f = rmv._fmt
    tools = f"{f(r['tool_calls'])} ({f(r['tool_errors'])})" if r["executed"] else "not run"
    failure = r["failure_category"] or ("—" if r["task_success"] else r["failure_reason"])
    checks = ", ".join(f"{c['name']} {'✓' if c['passed'] else '✗'}" for c in r["checks"])
    return (
        f"| {r['phase']} | {r['task']} | {f(r['task_success'])} | {f(r['test_success'])} "
        f"| {f(r['score'])} | {tools} | {f(r['steps'])} | {f(r['llm_retries'])} "
        f"| {f(r['duration_seconds'])} | {f(r['avg_llm_latency_ms'])} "
        f"| {f(r['input_tokens'])} / {f(r['output_tokens'])} / {f(r['total_tokens'])} "
        f"| {f(r['actual_cost_usd'])} | {failure or '—'} | {checks or rmv.NOT_AVAILABLE} |"
    )


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# LIMITED REAL-MODEL IMPROVEMENT EXPERIMENT — results",
        "",
        f"**REAL MODEL** · Provider: **OpenCode Go** · Model: **{MODEL_NAME}** "
        f"(`{MODEL_ID}`). Offline/scripted results are stored separately.",
        "",
        f"- Date: {summary['started_at']} to {summary['finished_at']}",
        f"- AgentForge: {summary['agentforge_version']} (commit `{summary['commit']}`)",
        f"- Endpoint: `{summary['base_url']}`; authentication: {summary['auth_mode']}",
        f"- Suite: `{summary['suite']}` v1, tasks: {', '.join(summary['tasks'])}",
        f"- Task executions: {summary['executions']} (limit {summary['max_executions']}); "
        "model-call retries: none; token budget per task: "
        f"{summary['token_budget']}",
        f"- Sandbox: {summary['sandbox']}",
        f"- Secret scan of stored results and logs: {summary['secret_scan']}",
        "",
        "| Version | Task | Success | Tests | Score | Tool calls (errors) | Steps | Retries "
        "| Duration (s) | Avg model-call latency (ms) | Tokens in/out/total | Cost | Failure "
        "| Checks |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    lines += [_row_line(r) for r in summary["v1_rows"] + summary.get("v2_rows", [])]
    if summary.get("stopped"):
        lines += ["", f"**Stopped after v1:** {summary['stopped']}"]
    cycle = summary.get("cycle")
    if cycle:
        lines += ["", "## Failure analysis (v1)", ""]
        for category, count in cycle["analysis"]["categories"].items():
            lines.append(f"- `{category}`: {count} run(s)")
        for failure in cycle["analysis"]["failures"]:
            evidence = "; ".join(failure["evidence"][:2]).replace("\n", " ")[:300]
            lines.append(f"  - {failure['task_id']}: {failure['summary']} — {evidence}")
        lines += ["", "## Proposal", ""]
        for change in cycle["proposal"]["changes"]:
            applied = change["id"] in (cycle.get("applied_change_ids") or [])
            lines.append(
                f"- `{change['id']}` {change['operation']} `{change['path']}` "
                f"({'applied' if applied else 'not applied'}): {change['rationale']}"
            )
        comparison = cycle.get("comparison")
        if comparison:
            lines += ["", f"## Comparison: verdict `{comparison['verdict']}`", ""]
            for task in comparison.get("tasks", []):
                lines.append(
                    f"- {task['task_id']}: {task['baseline_passed']}/{task['baseline_runs']} -> "
                    f"{task['candidate_passed']}/{task['candidate_runs']} ({task['change']})"
                )
            lines += [f"- note: {note}" for note in comparison.get("notes", [])]
    lines += ["", f"Cost: {rmv.NOT_AVAILABLE} (AgentForge does not read billing).", ""]
    return "\n".join(lines)


def _docker_problem() -> str | None:
    if shutil.which("docker") is None:
        return "docker is not installed"
    probe = subprocess.run(  # noqa: S603
        ["docker", "image", "inspect", SANDBOX_IMAGE],  # noqa: S607
        capture_output=True,
        check=False,
    )
    return None if probe.returncode == 0 else f"image {SANDBOX_IMAGE} is not available"


async def main_async(args: argparse.Namespace, data_dir: Path) -> dict[str, Any]:
    from agentforge import __version__
    from agentforge.settings import Settings
    from agentforge.storage import Database

    base_url = args.base_url or rmv.BASE_URL
    config = v1_config(
        base_url=base_url, auth=args.auth, token_budget=args.token_budget, sandbox=args.sandbox
    )
    settings = Settings(data_dir=data_dir, _env_file=None)  # type: ignore[call-arg]
    db = Database(settings.resolved_database_url)
    await db.migrate()
    budget = ExecutionBudget(MAX_EXECUTIONS)
    started = datetime.now(UTC)
    try:
        out = await run_experiment(
            db=db, settings=settings, config=config, results=Path(args.results), budget=budget
        )
    finally:
        await db.dispose()
    rows = out.pop("v1_rows"), out.pop("v2_rows", [])
    return {
        "experiment": "Limited Real-Model Improvement Experiment",
        "result_class": "real",
        "provider": rmv.PROVIDER_LABEL,
        "provider_id": rmv.PROVIDER,
        "model": MODEL_NAME,
        "model_id": MODEL_ID,
        "base_url": base_url,
        "auth_mode": rmv.AUTH_MODES[args.auth],
        "agentforge_version": __version__,
        "commit": rmv._commit(),
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "suite": str(SUITE_FILE.relative_to(ROOT)),
        "tasks": TASKS,
        "max_executions": MAX_EXECUTIONS,
        "executions": sum(1 for r in rows[0] + rows[1] if r.executed),
        "token_budget": args.token_budget,
        "sandbox": f"{args.sandbox} ({SANDBOX_IMAGE}, network none)",
        "secret_scan": "pending",
        **out,
        "v1_rows": [r.__dict__ for r in rows[0]],
        "v2_rows": [r.__dict__ for r in rows[1]],
    }


def main(argv: list[str] | None = None) -> int:
    from agentforge.observability.logging import JsonFormatter, configure_logging
    from agentforge.observability.redaction import Redactor

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", help=f"OpenAI-compatible endpoint (default: {rmv.BASE_URL})")
    parser.add_argument("--auth", choices=sorted(rmv.AUTH_MODES), default=rmv.AUTH_ENV)
    parser.add_argument("--results", default=str(ROOT / "dogfood" / "results"))
    parser.add_argument("--data-dir", default=str(ROOT / ".agentforge" / "real-improvement"))
    parser.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    parser.add_argument("--sandbox", choices=["docker", "local"], default="docker")
    args = parser.parse_args(argv)

    if args.auth == rmv.AUTH_ENV and not os.environ.get(rmv.KEY_ENV):
        print(
            f"not run: {rmv.PROVIDER_LABEL} credentials are not configured "
            "(use --auth proxy if an egress proxy injects them). No model was called."
        )
        return 2
    if args.auth == rmv.AUTH_PROXY and not (
        os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    ):
        print("not run: --auth proxy needs an egress proxy (HTTPS_PROXY). No model was called.")
        return 2
    if args.sandbox == "docker" and (problem := _docker_problem()):
        print(f"not run: {problem}. No model was called.")
        return 2

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    configure_logging("INFO")
    file_handler = logging.FileHandler(data_dir / "experiment.log")
    file_handler.setFormatter(JsonFormatter(Redactor.from_environment()))
    logging.getLogger("agentforge").addHandler(file_handler)

    summary = asyncio.run(main_async(args, data_dir))
    results_root = Path(args.results)
    stamp = summary["started_at"].replace(":", "").replace("-", "").replace("+0000", "Z")
    out_dir = results_root / "real" / f"improvement-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    scan_key = os.environ.get(rmv.KEY_ENV)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    leaked = rmv.credential_pattern_found([results_root / "real", data_dir]) or bool(
        scan_key and rmv.secret_found([results_root, data_dir], scan_key)
    )
    summary["secret_scan"] = "FOUND" if leaked else "clean"
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    (out_dir / "summary.md").write_text(render_markdown(summary))
    print(f"summary: {out_dir / 'summary.md'}")
    print(f"task executions: {summary['executions']} (limit {MAX_EXECUTIONS})")
    if leaked:
        print("secret scan: FOUND - a credential appears in stored results or logs; delete them.")
        return 1
    print("secret scan: clean")
    if str(summary.get("stopped", "")).startswith("authentication failed"):
        print("Stopped: authentication failed; no further model calls were made.")
        return 3
    print("Stopped: the experiment is complete. No further model calls will be made.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
