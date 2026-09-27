#!/usr/bin/env python3
"""Limited Real-Model Validation (see docs/REAL_MODEL_BENCHMARK.md).

Runs, sequentially and at most once each:

- one smoke task per model (``starter/create-greeting``), and
- only for models whose smoke task passed, two existing benchmark tasks
  (``dogfood-coding/add-cli-flag`` and ``dogfood-debugging/pagination-off-by-one``),

for at most 15 task executions in total. Every model gets the same task
definitions, evaluators, system prompts and limits. Failed model calls are not
retried (``retry.llm_max_attempts = 1``) and each task has a token budget.

Before any task runs, the OpenAI-compatible endpoint is checked with
``GET <base>/models`` (lists models, invokes none): it verifies the key and
which requested model ids exist. The key is read from ``OPENCODE_API_KEY`` and
is never printed or written anywhere.

    OPENCODE_API_KEY=... uv run python scripts/real_model_validation.py --base-url URL
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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
KEY_ENV = "OPENCODE_API_KEY"
PROVIDER = "opencode-go"
PROVIDER_LABEL = "OpenCode Go"
MAX_EXECUTIONS = 15
DEFAULT_TOKEN_BUDGET = 150_000
SANDBOX_IMAGE = "python:3.12-slim"  # the tasks below need only python3
# Tried in order by the preflight listing (never with a model call); the one
# that lists the requested models is used and recorded.
CANDIDATE_BASE_URLS = ["https://opencode.ai/zen/go/v1", "https://opencode.ai/zen/v1"]

MODELS: list[tuple[str, str]] = [
    ("DeepSeek V4.1 Flash", "opencode-go/deepseek-v4.1-flash"),
    ("MiMo-V2.6-Flash", "opencode-go/mimo-v2.6-flash"),
    ("Muse Spark 1.3 Contributor", "opencode-go/muse-spark-1.3-contributor"),
    ("GLM-5.3 Flash", "opencode-go/glm-5.3-flash"),
    ("Kimi K2.7 Code", "opencode-go/kimi-k2.7-code"),
]


@dataclass(frozen=True)
class TaskRef:
    phase: str
    suite: str
    task: str
    agent: str


SMOKE = TaskRef(
    "smoke", "examples/benchmarks/starter.yaml", "create-greeting", "dogfood/agents/coding.yaml"
)
TASK_A = TaskRef(
    "task-a", "dogfood/benchmarks/coding.yaml", "add-cli-flag", "dogfood/agents/coding.yaml"
)
TASK_B = TaskRef(
    "task-b",
    "dogfood/benchmarks/debugging.yaml",
    "pagination-off-by-one",
    "dogfood/agents/debugging.yaml",
)

# AgentForge failure category -> the experiment's failure taxonomy (automatic;
# finer distinctions such as planning vs reasoning need a trace review).
FAILURE_TAXONOMY = {
    "setup": "infrastructure failure",
    "internal": "infrastructure failure",
    "cancelled": "infrastructure failure",
    "missing_record": "infrastructure failure",
    "llm_error": "provider/API failure",
    "llm_refusal": "provider/API failure (refusal)",
    "timeout": "timeout",
    "step_limit": "step-limit failure",
    "tool_budget": "step-limit failure",
    "inefficient": "step-limit failure",
    "token_budget": "stopped by resource guard (token budget)",
    "tool_errors": "tool execution failure",
    "tests_failed": "test failure",
    "workspace_state": "coding failure",
    "wrong_output": "reasoning failure",
    "judge_rejected": "reasoning failure",
    "no_final_answer": "planning failure",
    "process_not_followed": "tool selection failure",
    "evaluation_failed": "evaluator failure",
    "not_evaluated": "evaluator failure",
}


class PreflightError(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


# ---------------------------------------------------------------- preflight
def resolve_model_id(requested: str, available: set[str]) -> str | None:
    """The id to send in the API ``model`` field, if the endpoint lists it."""
    if requested in available:
        return requested
    short = requested.split("/", 1)[1] if "/" in requested else requested
    return short if short in available else None


async def list_models(
    base_url: str, key: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> set[str]:
    url = base_url.rstrip("/") + "/models"
    async with httpx.AsyncClient(timeout=30, transport=transport) as client:
        try:
            response = await client.get(url, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as exc:
            raise PreflightError("infrastructure failure", f"{url}: {type(exc).__name__}") from exc
    if response.status_code in (401, 403):
        raise PreflightError("configuration failure", f"{url}: HTTP {response.status_code}")
    if response.status_code != 200:
        raise PreflightError("provider/API failure", f"{url}: HTTP {response.status_code}")
    try:
        data = response.json().get("data", [])
        return {str(item["id"]) for item in data if isinstance(item, dict) and "id" in item}
    except (ValueError, AttributeError) as exc:
        raise PreflightError("provider/API failure", f"{url}: not an OpenAI model list") from exc


async def preflight(
    base_urls: list[str], key: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[str, set[str]]:
    """First endpoint that authenticates and lists at least one requested model."""
    errors: list[str] = []
    for base_url in base_urls:
        try:
            available = await list_models(base_url, key, transport=transport)
        except PreflightError as exc:
            errors.append(f"{exc.kind}: {exc.message}")
            continue
        if any(resolve_model_id(model_id, available) for _, model_id in MODELS):
            return base_url, available
        errors.append(f"{base_url}: none of the requested models is listed")
    raise PreflightError("configuration failure", "; ".join(errors))


# --------------------------------------------------------------- execution
def experiment_config(
    agent_file: Path, *, api_model: str, base_url: str, token_budget: int, sandbox: str
) -> Any:
    """The dogfood agent config with the provider/model swapped in - identical for every model."""
    from agentforge.config_files import load_agent_config
    from agentforge.core.config import AgentConfig

    data = load_agent_config(agent_file).model_dump(mode="json")
    data["model"].update(
        {"provider": PROVIDER, "model": api_model, "base_url": base_url, "api_key_env": KEY_ENV}
    )
    data["retry"]["llm_max_attempts"] = 1  # no automatic retries of model calls
    data["retry"]["evaluation_retries"] = 0
    data["limits"]["max_total_tokens"] = token_budget
    data["sandbox"].update({"kind": sandbox, "image": SANDBOX_IMAGE, "network": "none"})
    data["labels"] = {**data.get("labels", {}), "experiment": "limited-real-model-validation"}
    return AgentConfig.model_validate(data)


@dataclass
class Row:
    model: str
    model_id: str
    phase: str
    suite: str
    task: str
    api_model: str | None = None
    executed: bool = False
    benchmark_run_id: str | None = None
    run_id: str | None = None
    status: str | None = None
    task_success: bool | None = None
    test_success: bool | None = None
    score: float | None = None
    tool_calls: int | None = None
    tool_errors: int | None = None
    tool_success_rate: float | None = None
    steps: int | None = None
    llm_retries: int | None = None
    evaluation_retries: int | None = None
    duration_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    actual_cost_usd: float | None = None
    timeout: bool | None = None
    step_limit_hit: bool | None = None
    failure_category: str | None = None
    agentforge_category: str | None = None
    failure_reason: str | None = None
    checks: list[dict[str, Any]] = field(default_factory=list)
    tool_usage: dict[str, dict[str, int]] = field(default_factory=dict)


def fill_row(row: Row, bench: Any, run: Any, report: Any) -> None:
    from agentforge.improvement.analysis import classify_run

    record = report.runs[0]
    row.executed = True
    row.benchmark_run_id = bench.id
    row.run_id = record.run_id
    row.status = record.status
    row.task_success = record.success
    row.score = record.score
    row.tool_calls = record.tool_calls
    row.tool_errors = record.tool_errors
    row.steps = record.steps
    row.llm_retries = record.llm_retries
    row.evaluation_retries = record.evaluation_retries
    row.duration_seconds = record.duration_seconds
    row.input_tokens = record.input_tokens
    row.output_tokens = record.output_tokens
    row.estimated_cost_usd = record.estimated_cost_usd
    row.actual_cost_usd = record.actual_cost_usd
    row.checks = [c.model_dump(mode="json") for c in record.checks]
    if run is None:
        return
    row.tool_success_rate = run.metrics.tool_success_rate
    row.timeout = run.status.value == "timed_out"
    row.step_limit_hit = bool(run.error and run.error.type == "max_steps")
    command_checks = {
        str(spec.get("name") or spec.get("type"))
        for spec in run.evaluators
        if spec.get("type") == "command"
    }
    results = [c for c in record.checks if c.name in command_checks]
    row.test_success = all(c.passed for c in results) if results else None
    for call in run.tool_calls:
        counts = row.tool_usage.setdefault(call.tool, {})
        counts[call.status.value] = counts.get(call.status.value, 0) + 1
    failure = classify_run(run) if not record.success else None
    if failure is not None:
        row.agentforge_category = failure.category.value
        row.failure_category = FAILURE_TAXONOMY.get(failure.category.value, "unclassified")
        row.failure_reason = (failure.evidence or [failure.summary])[0]


async def execute(db: Any, settings: Any, config: Any, ref: TaskRef, row: Row) -> None:
    from agentforge.benchmarks import BenchmarkRunner, load_suite
    from agentforge.benchmarks.report import build_report
    from agentforge.storage import RunRepository
    from agentforge.storage.tracking import StorageRecorder

    suite = load_suite(ROOT / ref.suite)
    bench = await BenchmarkRunner(settings, recorder=StorageRecorder(db)).run(
        suite, config, repeats=1, task_ids=[ref.task]
    )
    page = await RunRepository(db).list(benchmark_run_id=bench.id, limit=10)
    runs = {r.id: r for r in page.items}
    report = build_report(bench, runs)
    fill_row(row, bench, runs.get(report.runs[0].run_id), report)


async def run_experiment(
    *,
    db: Any,
    settings: Any,
    base_url: str,
    available: set[str],
    token_budget: int,
    sandbox: str,
    make_config: Any = experiment_config,
    models: list[tuple[str, str]] | None = None,
    max_executions: int = MAX_EXECUTIONS,
) -> list[Row]:
    """Sequential execution under a hard cap; benchmarks only after a passed smoke task."""
    rows: list[Row] = []
    executions = 0
    for name, model_id in models or MODELS:
        api_model = resolve_model_id(model_id, available)
        smoke_passed = False
        for ref in (SMOKE, TASK_A, TASK_B):
            row = Row(
                model=name,
                model_id=model_id,
                phase=ref.phase,
                suite=ref.suite,
                task=ref.task,
                api_model=api_model,
            )
            rows.append(row)
            if api_model is None:
                row.failure_category = "configuration failure"
                row.failure_reason = "model id not listed by the endpoint; no model call made"
                continue
            if ref is not SMOKE and not smoke_passed:
                row.failure_reason = "not run: the smoke task did not pass"
                continue
            if executions >= max_executions:
                row.failure_reason = f"not run: execution cap ({max_executions}) reached"
                continue
            executions += 1
            config = make_config(
                ROOT / ref.agent,
                api_model=api_model,
                base_url=base_url,
                token_budget=token_budget,
                sandbox=sandbox,
            )
            print(f"[{executions}/{max_executions}] {name} · {ref.phase} · {ref.task}", flush=True)
            try:
                await execute(db, settings, config, ref, row)
            except Exception as exc:  # recorded, never retried
                row.executed = True
                row.failure_category = "infrastructure failure"
                row.failure_reason = f"{type(exc).__name__}: {exc}"
            if ref is SMOKE:
                smoke_passed = bool(row.task_success)
            print(f"    -> success={row.task_success} {row.failure_category or ''}", flush=True)
    return rows


# ----------------------------------------------------------------- output
def _fmt(value: Any) -> str:
    if value is None:
        return "not available"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Limited Real-Model Validation — results",
        "",
        "**REAL MODEL** results. Provider: **OpenCode Go** (`opencode-go`). Offline/scripted",
        "results are stored separately and are not part of this file.",
        "",
        f"- Date: {summary['started_at']} to {summary['finished_at']}",
        f"- AgentForge: {summary['agentforge_version']} (commit `{summary['commit']}`)",
        f"- Endpoint: `{summary['base_url']}`",
        f"- Task executions: {summary['executions']} (cap {summary['max_executions']})",
        f"- Token budget per task: {summary['token_budget']}; model-call retries: none",
        f"- Secret scan of stored results and logs: {summary['secret_scan']}",
        "",
        "| Model | Phase | Task | Success | Tests | Score | Tool calls (errors) | Steps "
        "| Retries | Duration (s) | Tokens in/out | Cost | Failure |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in summary["rows"]:
        retries = None
        if r["llm_retries"] is not None:
            retries = r["llm_retries"] + (r["evaluation_retries"] or 0)
        tools = (
            "not run"
            if not r["executed"]
            else f"{_fmt(r['tool_calls'])} ({_fmt(r['tool_errors'])})"
        )
        failure = r["failure_category"] or ("—" if r["task_success"] else r["failure_reason"])
        lines.append(
            f"| REAL MODEL · {r['model']} (`{r['model_id']}`) | {r['phase']} | {r['task']} "
            f"| {_fmt(r['task_success']) if r['executed'] else 'not run'} "
            f"| {_fmt(r['test_success']) if r['executed'] else 'not run'} | {_fmt(r['score'])} "
            f"| {tools} | {_fmt(r['steps'])} | {_fmt(retries)} | {_fmt(r['duration_seconds'])} "
            f"| {_fmt(r['input_tokens'])} / {_fmt(r['output_tokens'])} "
            f"| {_fmt(r['actual_cost_usd'])} | {failure or '—'} |"
        )
    lines += ["", "Cost: actual cost is not available (AgentForge does not read billing).", ""]
    return "\n".join(lines)


def scan_for_secret(paths: list[Path], secret: str) -> list[Path]:
    """Files under ``paths`` that contain ``secret`` (byte-level)."""
    needle = secret.encode()
    hits: list[Path] = []
    for root in paths:
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for path in files:
            try:
                if needle in path.read_bytes():
                    hits.append(path)
            except OSError:
                continue
    return hits


def _commit() -> str:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out.stdout.strip()


def _docker_problem() -> str | None:
    if shutil.which("docker") is None:
        return "docker is not installed"
    probe = subprocess.run(  # noqa: S603
        ["docker", "image", "inspect", SANDBOX_IMAGE],  # noqa: S607
        capture_output=True,
        check=False,
    )
    return None if probe.returncode == 0 else f"image {SANDBOX_IMAGE} is not available"


async def main_async(args: argparse.Namespace, key: str, data_dir: Path) -> dict[str, Any] | int:
    from agentforge import __version__
    from agentforge.benchmarks.report import build_report, save_report
    from agentforge.settings import Settings
    from agentforge.storage import Database, RunRepository
    from agentforge.storage.tracking import BenchmarkRepository

    base_urls = [args.base_url] if args.base_url else CANDIDATE_BASE_URLS
    try:
        base_url, available = await preflight(base_urls, key)
    except PreflightError as exc:
        print(f"preflight failed ({exc.kind}): {exc.message}. No model was called.")
        return 2
    print(f"endpoint {base_url}: {len(available)} models listed")

    settings = Settings(data_dir=data_dir, _env_file=None)  # type: ignore[call-arg]
    db = Database(settings.resolved_database_url)
    await db.migrate()
    started = datetime.now(UTC)
    try:
        rows = await run_experiment(
            db=db,
            settings=settings,
            base_url=base_url,
            available=available,
            token_budget=args.token_budget,
            sandbox=args.sandbox,
        )
        for row in rows:
            if row.benchmark_run_id:
                bench = await BenchmarkRepository(db).get(row.benchmark_run_id)
                page = await RunRepository(db).list(benchmark_run_id=bench.id, limit=10)
                save_report(Path(args.results), build_report(bench, {r.id: r for r in page.items}))
    finally:
        await db.dispose()
    return {
        "experiment": "Limited Real-Model Validation",
        "result_class": "real",
        "provider": PROVIDER_LABEL,
        "provider_id": PROVIDER,
        "base_url": base_url,
        "agentforge_version": __version__,
        "commit": _commit(),
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "max_executions": MAX_EXECUTIONS,
        "executions": sum(1 for r in rows if r.executed),
        "token_budget": args.token_budget,
        "sandbox": f"{args.sandbox} ({SANDBOX_IMAGE}, network none)",
        "tasks": {ref.phase: f"{ref.suite}::{ref.task}" for ref in (SMOKE, TASK_A, TASK_B)},
        "secret_scan": "pending",
        "rows": [r.__dict__ for r in rows],
    }


def main(argv: list[str] | None = None) -> int:
    from agentforge.observability.logging import JsonFormatter, configure_logging
    from agentforge.observability.redaction import Redactor

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--base-url", help=f"OpenAI-compatible endpoint (default: try {CANDIDATE_BASE_URLS})"
    )
    parser.add_argument("--results", default=str(ROOT / "dogfood" / "results"))
    parser.add_argument("--data-dir", default=str(ROOT / ".agentforge" / "real-model-validation"))
    parser.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    parser.add_argument("--sandbox", choices=["docker", "local"], default="docker")
    args = parser.parse_args(argv)

    key = os.environ.get(KEY_ENV)
    if not key:
        print(f"not run: {PROVIDER_LABEL} credentials are not configured. No model was called.")
        return 2
    if args.sandbox == "docker" and (problem := _docker_problem()):
        print(f"not run: {problem}. No model was called.")
        return 2

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    configure_logging("INFO")
    file_handler = logging.FileHandler(data_dir / "validation.log")
    file_handler.setFormatter(JsonFormatter(Redactor.from_environment()))
    logging.getLogger("agentforge").addHandler(file_handler)

    result = asyncio.run(main_async(args, key, data_dir))
    if isinstance(result, int):
        return result
    summary = result
    results_root = Path(args.results)  # reports go to <root>/real/..., never <root>/offline
    stamp = summary["started_at"].replace(":", "").replace("-", "").replace("+0000", "Z")
    out_dir = results_root / "real" / f"limited-validation-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    leaks = scan_for_secret([results_root, data_dir], key)
    summary["secret_scan"] = "clean" if not leaks else f"FOUND in {len(leaks)} file(s)"
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    (out_dir / "summary.md").write_text(render_markdown(summary))
    print(f"summary: {out_dir / 'summary.md'}  secret scan: {summary['secret_scan']}")
    print("Stopped: the limited validation is complete. No further model calls will be made.")
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main())
