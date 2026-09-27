#!/usr/bin/env python3
"""Limited Real-Model Validation (see docs/REAL_MODEL_BENCHMARK.md).

Runs, sequentially and at most once each:

- one smoke task per model (``starter/create-greeting``), and
- only for models whose smoke task passed, two existing benchmark tasks
  (``dogfood-coding/add-cli-flag`` and ``dogfood-debugging/pagination-off-by-one``),

for at most 15 task executions in total (``--plan validation``, the default).

``--plan benchmark`` runs only the two benchmark tasks for every model, once
each (at most 10 task executions), with no model listing and no smoke task.

Every model gets the same task definitions, evaluators, system prompts and
limits. Failed model calls are not retried (``retry.llm_max_attempts = 1``)
and each task has a token budget.

Before any task runs, ``GET <base>/models`` (lists models, invokes none)
checks that the endpoint is reachable and which requested model ids exist.
OpenCode serves that listing without authentication, so it is NOT evidence that
the credential works: authentication is only established by the first model
call, and a 401/403 there stops the experiment before any further call.

Authentication modes (``--auth``):

- ``env`` (default): the key is read from ``OPENCODE_API_KEY`` and sent as a
  bearer token. It is never printed or written anywhere.
- ``proxy``: an egress proxy injects the credential into requests to
  opencode.ai (a Claude Cloud environment's API Credentials). The key is never
  in this process: nothing reads ``OPENCODE_API_KEY`` and requests carry no
  ``Authorization`` header. Requires ``HTTPS_PROXY``.

    OPENCODE_API_KEY=... uv run python scripts/real_model_validation.py
    uv run python scripts/real_model_validation.py --auth proxy
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
AUTH_ENV = "env"
AUTH_PROXY = "proxy"
AUTH_MODES = {
    AUTH_ENV: f"env ({KEY_ENV})",
    AUTH_PROXY: "proxy (credential injected by the egress proxy; no key in this process)",
}
PROVIDER = "opencode-go"
PROVIDER_LABEL = "OpenCode Go"
MAX_EXECUTIONS = 15
BENCHMARK_MAX_EXECUTIONS = 10
DEFAULT_TOKEN_BUDGET = 150_000
SANDBOX_IMAGE = "python:3.12-slim"  # the tasks below need only python3
BASE_URL = "https://opencode.ai/zen/go/v1"
# Model call rejections that mean the credential does not work.
AUTH_ERROR_TYPES = {"llm.authentication", "llm.permission"}

# Exact ids as listed by GET <BASE_URL>/models; sent verbatim as the API model.
MODELS: list[tuple[str, str]] = [
    ("DeepSeek V4.1 Flash", "deepseek-v4.1-flash"),
    ("MiMo-V2.6-Flash", "mimo-v2.6-flash"),
    ("Muse Spark 1.3 Contributor", "muse-spark-1.3-contributor"),
    ("GLM-5.3 Flash", "glm-5.3-flash"),
    ("Kimi K2.7 Code", "kimi-k2.7-code"),
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
    """The id to send in the API ``model`` field: exact match with the listing only."""
    return requested if requested in available else None


async def list_models(
    base_url: str, key: str | None, *, transport: httpx.AsyncBaseTransport | None = None
) -> set[str]:
    """The listed model ids. ``key`` is None in proxy mode (no header is sent).

    A 200 here says nothing about the credential: the listing is unauthenticated.
    """
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with httpx.AsyncClient(timeout=30, transport=transport) as client:
        try:
            response = await client.get(url, headers=headers)
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
    base_url: str, key: str | None, *, transport: httpx.AsyncBaseTransport | None = None
) -> set[str]:
    """Reachability and model availability of the one endpoint (not authentication)."""
    available = await list_models(base_url, key, transport=transport)
    if not any(resolve_model_id(model_id, available) for _, model_id in MODELS):
        raise PreflightError("configuration failure", f"{base_url}: no requested model is listed")
    return available


# --------------------------------------------------------------- execution
def experiment_config(
    agent_file: Path,
    *,
    api_model: str,
    base_url: str,
    token_budget: int,
    sandbox: str,
    auth: str = AUTH_ENV,
) -> Any:
    """The dogfood agent config with the provider/model swapped in - identical for every model."""
    from agentforge.config_files import load_agent_config
    from agentforge.core.config import AgentConfig

    data = load_agent_config(agent_file).model_dump(mode="json")
    data["model"].update(
        {
            "provider": PROVIDER,
            "model": api_model,
            "base_url": base_url,
            "api_key_env": KEY_ENV if auth == AUTH_ENV else None,
            "options": {
                **data["model"].get("options", {}),
                "auth": "api_key" if auth == AUTH_ENV else "proxy",
            },
        }
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
    auth_failed: bool = False
    total_tokens: int | None = None
    llm_calls: int | None = None
    avg_llm_latency_ms: float | None = None
    token_limit_hit: bool | None = None
    provider_error: str | None = None
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
    row.token_limit_hit = bool(run.error and run.error.type == "token_budget")
    if row.input_tokens is not None and row.output_tokens is not None:
        row.total_tokens = row.input_tokens + row.output_tokens
    calls = [s.llm_call for s in run.steps if s.llm_call is not None]
    row.llm_calls = len(calls)
    if calls:
        row.avg_llm_latency_ms = sum(c.latency_ms for c in calls) / len(calls)
    if run.error is not None and run.error.type.startswith("llm."):
        row.provider_error = f"{run.error.type}: {run.error.message}"
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
    if run.error is not None and run.error.type in AUTH_ERROR_TYPES:
        row.auth_failed = True
        row.failure_category = "configuration failure (authentication)"


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
    auth: str = AUTH_ENV,
    phases: tuple[TaskRef, ...] = (SMOKE, TASK_A, TASK_B),
) -> list[Row]:
    """Sequential execution under a hard cap. With a smoke phase, a model's
    benchmark tasks run only after its smoke task passed.

    A model call rejected with 401/403 stops everything: no further calls are made.
    """
    rows: list[Row] = []
    executions = 0
    auth_failed = False
    for name, model_id in models or MODELS:
        api_model = resolve_model_id(model_id, available)
        smoke_passed = SMOKE not in phases
        for ref in phases:
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
            if auth_failed:
                row.failure_reason = "not run: an earlier model call was rejected (HTTP 401/403)"
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
                auth=auth,
            )
            print(f"[{executions}/{max_executions}] {name} · {ref.phase} · {ref.task}", flush=True)
            try:
                await execute(db, settings, config, ref, row)
            except Exception as exc:  # recorded, never retried
                row.executed = True
                row.failure_category = "infrastructure failure"
                row.failure_reason = f"{type(exc).__name__}: {exc}"
            auth_failed = row.auth_failed
            if ref is SMOKE:
                smoke_passed = bool(row.task_success)
            print(f"    -> success={row.task_success} {row.failure_category or ''}", flush=True)
    return rows


# ----------------------------------------------------------------- output
NOT_AVAILABLE = "NOT AVAILABLE"


def _fmt(value: Any) -> str:
    if value is None:
        return NOT_AVAILABLE
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"# LIMITED REAL-MODEL VALIDATION — results (plan: {summary['plan']})",
        "",
        "**REAL MODEL** results. Provider: **OpenCode Go** (`opencode-go`). Offline/scripted",
        "results are stored separately and are not part of this file.",
        "",
        f"- Date: {summary['started_at']} to {summary['finished_at']}",
        f"- AgentForge: {summary['agentforge_version']} (commit `{summary['commit']}`)",
        f"- Endpoint: `{summary['base_url']}`",
        f"- Authentication: {summary['auth_mode']}; {summary['authentication']}",
        f"- Task executions: {summary['executions']} (cap {summary['max_executions']})",
        f"- Token budget per task: {summary['token_budget']}; model-call retries: none",
        f"- Secret scan of stored results and logs: {summary['secret_scan']}",
        "",
        "| Model | Phase | Task | Success | Tests | Score | Tool calls (errors) | Steps "
        "| Retries | Duration (s) | Avg model-call latency (ms) | Tokens in/out/total | Cost "
        "| Failure |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
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
            f"| REAL MODEL · OpenCode Go · {r['model']} (`{r['model_id']}`) | {r['phase']} "
            f"| {r['task']} "
            f"| {_fmt(r['task_success']) if r['executed'] else 'not run'} "
            f"| {_fmt(r['test_success']) if r['executed'] else 'not run'} | {_fmt(r['score'])} "
            f"| {tools} | {_fmt(r['steps'])} | {_fmt(retries)} | {_fmt(r['duration_seconds'])} "
            f"| {_fmt(r['avg_llm_latency_ms'])} "
            f"| {_fmt(r['input_tokens'])} / {_fmt(r['output_tokens'])} / {_fmt(r['total_tokens'])} "
            f"| {_fmt(r['actual_cost_usd'])} | {failure or '—'} |"
        )
    lines += ["", f"Cost: {NOT_AVAILABLE} (AgentForge does not read billing).", ""]
    return "\n".join(lines)


def _files(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in paths:
        if root.is_file():
            found.append(root)
        elif root.is_dir():
            found.extend(p for p in root.rglob("*") if p.is_file())
    return found


def secret_found(paths: list[Path], secret: str) -> bool:
    """Whether any file under ``paths`` contains ``secret`` (byte-level).

    Returns only a boolean so nothing derived from the secret reaches output.
    """
    needle = secret.encode()
    for path in _files(paths):
        try:
            if needle in path.read_bytes():
                return True
        except OSError:
            continue
    return False


def credential_pattern_found(paths: list[Path]) -> bool:
    """Whether any file under ``paths`` holds a credential-shaped string.

    Uses the Redactor's patterns (bearer tokens, vendor key formats). This is the
    scan that still works in proxy mode, where the key itself is never known here.
    """
    from agentforge.observability.redaction import Redactor

    redactor = Redactor()
    for path in _files(paths):
        try:
            text = path.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        if redactor.redact_text(text) != text:
            return True
    return False


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


async def main_async(
    args: argparse.Namespace, key: str | None, data_dir: Path
) -> dict[str, Any] | int:
    from agentforge import __version__
    from agentforge.benchmarks.report import build_report, save_report
    from agentforge.settings import Settings
    from agentforge.storage import Database, RunRepository
    from agentforge.storage.tracking import BenchmarkRepository

    base_url = args.base_url or BASE_URL
    benchmark_plan = args.plan == "benchmark"
    phases = (TASK_A, TASK_B) if benchmark_plan else (SMOKE, TASK_A, TASK_B)
    max_executions = BENCHMARK_MAX_EXECUTIONS if benchmark_plan else MAX_EXECUTIONS
    if benchmark_plan:
        # No listing: the ids were verified against /models before this plan runs.
        available = {model_id for _, model_id in MODELS}
        print(f"plan benchmark: {len(MODELS)} models x {len(phases)} tasks, no preflight")
    else:
        try:
            available = await preflight(base_url, key)
        except PreflightError as exc:
            print(f"preflight failed ({exc.kind}): {exc.message}. No model was called.")
            return 2
        print(f"endpoint {base_url}: reachable, {len(available)} models listed")
        print("authentication: not verified by the listing (it is unauthenticated); the first")
        print("model call verifies it, and a 401/403 there stops the run.")

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
            auth=args.auth,
            phases=phases,
            max_executions=max_executions,
        )
        for row in rows:
            if row.benchmark_run_id:
                bench = await BenchmarkRepository(db).get(row.benchmark_run_id)
                page = await RunRepository(db).list(benchmark_run_id=bench.id, limit=10)
                save_report(Path(args.results), build_report(bench, {r.id: r for r in page.items}))
    finally:
        await db.dispose()
    if any(r.auth_failed for r in rows):
        authentication = "FAILED (a model call was rejected with HTTP 401/403)"
    elif any(r.executed and (r.input_tokens or 0) > 0 for r in rows):
        authentication = "verified by a successful model call"
    else:
        authentication = "not verified (no model call succeeded)"
    return {
        "experiment": "Limited Real-Model Validation",
        "result_class": "real",
        "provider": PROVIDER_LABEL,
        "provider_id": PROVIDER,
        "base_url": base_url,
        "auth_mode": AUTH_MODES[args.auth],
        "authentication": authentication,
        "agentforge_version": __version__,
        "commit": _commit(),
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "plan": args.plan,
        "max_executions": max_executions,
        "executions": sum(1 for r in rows if r.executed),
        "token_budget": args.token_budget,
        "sandbox": f"{args.sandbox} ({SANDBOX_IMAGE}, network none)",
        "tasks": {ref.phase: f"{ref.suite}::{ref.task}" for ref in phases},
        "secret_scan": "pending",
        "rows": [r.__dict__ for r in rows],
    }


def main(argv: list[str] | None = None) -> int:
    from agentforge.observability.logging import JsonFormatter, configure_logging
    from agentforge.observability.redaction import Redactor

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", help=f"OpenAI-compatible endpoint (default: {BASE_URL})")
    parser.add_argument(
        "--plan",
        choices=["validation", "benchmark"],
        default="validation",
        help="validation: listing + smoke + gated tasks (<= 15); "
        f"benchmark: the two tasks for every model, no smoke (<= {BENCHMARK_MAX_EXECUTIONS})",
    )
    parser.add_argument(
        "--auth",
        choices=sorted(AUTH_MODES),
        default=AUTH_ENV,
        help=f"env: read {KEY_ENV}; proxy: the egress proxy injects the credential "
        "(Claude Cloud API Credentials), no key in this process",
    )
    parser.add_argument("--results", default=str(ROOT / "dogfood" / "results"))
    parser.add_argument("--data-dir", default=str(ROOT / ".agentforge" / "real-model-validation"))
    parser.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    parser.add_argument("--sandbox", choices=["docker", "local"], default="docker")
    args = parser.parse_args(argv)

    key: str | None = None
    if args.auth == AUTH_ENV:
        key = os.environ.get(KEY_ENV)
        if not key:
            print(
                f"not run: {PROVIDER_LABEL} credentials are not configured "
                "(use --auth proxy if an egress proxy injects them). No model was called."
            )
            return 2
    elif not (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")):
        print("not run: --auth proxy needs an egress proxy (HTTPS_PROXY). No model was called.")
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
    # Exact-value scan when the key is in the environment (it never is in proxy mode:
    # then only the pattern scan applies), plus a credential-pattern scan always -
    # limited to REAL results and this run's data (offline fixtures may hold fakes).
    scan_key = os.environ.get(KEY_ENV)
    leaked = credential_pattern_found([results_root / "real", data_dir]) or bool(
        scan_key and secret_found([results_root, data_dir], scan_key)
    )
    summary["secret_scan"] = "FOUND" if leaked else "clean"
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    (out_dir / "summary.md").write_text(render_markdown(summary))
    print(f"summary: {out_dir / 'summary.md'}")
    if leaked:
        print("secret scan: FOUND - a credential appears in stored results or logs; delete them.")
        return 1
    print("secret scan: clean")
    if any(r["auth_failed"] for r in summary["rows"]):
        print("Stopped: authentication failed (HTTP 401/403); no further model calls were made.")
        return 3
    print("Stopped: the limited validation is complete. No further model calls will be made.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
