"""The limited real-model improvement experiment, against a local fake OpenCode Go server.

No real model is called. The fake model answers every task with "Done." and no
tool calls, so v1 fails both hard tasks, the rule-based proposer derives a
change from those failures, v2 runs, and the cycle is compared - the complete
loop, under the 4-execution cap.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from tests.e2e.test_real_model_validation import (
    ALL_MODELS,
    FAKE_KEY,
    assert_key_nowhere,
    fake_app,
    serve,
)

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]


def load(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    scripts = str(ROOT / "scripts")
    monkeypatch.syspath_prepend(scripts)
    spec = importlib.util.spec_from_file_location(
        "real_improvement_experiment", ROOT / "scripts" / "real_improvement_experiment.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def run_main(module: ModuleType, base_url: str, tmp_path: Path, *extra: str) -> int:
    code: int = module.main(
        [
            "--base-url",
            base_url,
            "--results",
            str(tmp_path / "results"),
            "--data-dir",
            str(tmp_path / "data"),
            "--sandbox",
            "local",
            *extra,
        ]
    )
    return code


def summary_of(tmp_path: Path) -> dict[str, Any]:
    [path] = (tmp_path / "results" / "real").glob("improvement-*/summary.json")
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def test_full_cycle_under_the_execution_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[dict[str, Any]] = []
    module = load(monkeypatch)
    monkeypatch.setenv("OPENCODE_API_KEY", FAKE_KEY)
    with serve(fake_app(ALL_MODELS, set(), calls, auth="env")) as base_url:
        code = run_main(module, base_url, tmp_path)
    out = capsys.readouterr().out
    assert code == 0, out
    summary = summary_of(tmp_path)
    assert summary["executions"] == 4 == summary["max_executions"]
    assert summary["model_id"] == "deepseek-v4.1-flash" and summary["result_class"] == "real"
    assert [r["task"] for r in summary["v1_rows"]] == module.TASKS
    assert [r["task"] for r in summary["v2_rows"]] == module.TASKS
    assert all(not r["task_success"] for r in summary["v1_rows"] + summary["v2_rows"])
    assert all(r["llm_retries"] == 0 for r in summary["v1_rows"] + summary["v2_rows"])

    cycle = summary["cycle"]
    assert cycle["status"] == "evaluated" and cycle["from_version"] == 1
    assert cycle["to_version"] == 2
    assert cycle["baseline_benchmark_run_id"] == summary["v1_benchmark_run_id"]
    assert cycle["candidate_benchmark_run_id"] == summary["v2_benchmark_run_id"]
    assert cycle["analysis"]["failed"] == 2
    applied = set(cycle["applied_change_ids"])
    assert applied
    for change in cycle["proposal"]["changes"]:
        excluded = change["path"].startswith(module.EXCLUDED_CHANGE_PATHS)
        assert (change["id"] in applied) is not excluded
    assert cycle["comparison"]["verdict"] in {"unchanged", "inconclusive"}

    # Every model request: a session per run, one run per task execution.
    run_ids = {r["run_id"] for r in summary["v1_rows"] + summary["v2_rows"]}
    assert len(run_ids) == 4 and {c["session"] for c in calls} == run_ids
    assert {c["model"] for c in calls} == {"deepseek-v4.1-flash"}
    # Reports of both benchmarks stored as REAL results only.
    reports = list((tmp_path / "results" / "real" / "dogfood-hard-v1").glob("*.json"))
    assert len(reports) == 2
    assert not (tmp_path / "results" / "offline").exists()
    markdown = next((tmp_path / "results" / "real").glob("improvement-*/summary.md")).read_text()
    assert (
        "REAL MODEL" in markdown and "OpenCode Go" in markdown and "deepseek-v4.1-flash" in markdown
    )
    assert "## Comparison: verdict" in markdown
    assert summary["secret_scan"] == "clean"
    assert_key_nowhere(tmp_path, out)


def test_history_is_stored_and_v1_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agentforge.settings import Settings
    from agentforge.storage import AgentRepository, Database
    from agentforge.storage.tracking import BenchmarkRepository, ImprovementRepository

    module = load(monkeypatch)
    monkeypatch.setenv("OPENCODE_API_KEY", FAKE_KEY)
    with serve(fake_app(ALL_MODELS, set(), [], auth="env")) as base_url:
        assert run_main(module, base_url, tmp_path) == 0
    summary = summary_of(tmp_path)

    async def check() -> None:
        settings = Settings(data_dir=tmp_path / "data", _env_file=None)  # type: ignore[call-arg]
        db = Database(settings.resolved_database_url)
        try:
            agents = AgentRepository(db)
            agent = await agents.get(summary["agent_id"])
            versions = await agents.versions(agent.id)
            assert [v.version for v in versions] == [1, 2] or [v.version for v in versions] == [
                2,
                1,
            ]
            v1 = await agents.get_version(agent.id, 1)
            assert v1.config.model.model == "deepseek-v4.1-flash"
            assert v1.config.retry.llm_max_attempts == 1
            benches = BenchmarkRepository(db)
            b1 = await benches.get(summary["v1_benchmark_run_id"])
            b2 = await benches.get(summary["v2_benchmark_run_id"])
            assert (b1.agent_version, b2.agent_version) == (1, 2)
            assert b1.result_class.value == b2.result_class.value == "real"
            cycle = await ImprovementRepository(db).get(summary["cycle_id"])
            assert cycle.status.value == "evaluated" and cycle.comparison is not None
        finally:
            await db.dispose()

    asyncio.run(check())


def test_proxy_mode_sends_no_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[dict[str, Any]] = []
    module = load(monkeypatch)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")  # only https:// URLs use it
    with serve(fake_app(ALL_MODELS, set(), calls, auth="proxy")) as base_url:
        code = run_main(module, base_url, tmp_path, "--auth", "proxy")
    assert code == 0, capsys.readouterr().out
    assert calls and all(c["authorization"] is None for c in calls)
    assert summary_of(tmp_path)["auth_mode"].startswith("proxy")


def test_authentication_failure_stops_before_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[dict[str, Any]] = []
    module = load(monkeypatch)
    monkeypatch.setenv("OPENCODE_API_KEY", FAKE_KEY)
    app = fake_app(ALL_MODELS, set(), calls, auth="env", reject_auth=True)
    with serve(app) as base_url:
        code = run_main(module, base_url, tmp_path)
    assert code == 3, capsys.readouterr().out
    summary = summary_of(tmp_path)
    assert summary["executions"] == 2 and summary["v2_rows"] == []
    assert summary["stopped"].startswith("authentication failed")
    assert "cycle" not in summary
    assert len(calls) == 2  # one rejected call per v1 task, nothing after


def test_v1_passing_everything_stops_without_improvement(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load(monkeypatch)
    rows = [module.rmv.Row("m", "id", "v1", "s", t, task_success=True) for t in module.TASKS]
    assert "not difficult enough" in module.stop_reason_after_v1(rows)
    rows[0].task_success = False
    assert module.stop_reason_after_v1(rows) is None


def test_budget_and_excluded_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentforge.improvement.proposal import ProposedChange

    module = load(monkeypatch)
    budget = module.ExecutionBudget(4)
    budget.reserve(2)
    budget.reserve(2)
    with pytest.raises(module.BudgetExceededError):
        budget.reserve(1)

    proposal = SimpleNamespace(
        changes=[
            ProposedChange(id="c1", path="system_prompt", value="x"),
            ProposedChange(id="c2", path="retry.llm_max_attempts", value=3),
            ProposedChange(id="c3", path="limits.max_total_tokens", value=10**6),
            ProposedChange(id="c4", path="limits.max_steps", value=25),
        ]
    )
    assert module.applicable_changes(proposal) == ["c1", "c4"]


def test_config_has_no_retries_and_the_fixed_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load(monkeypatch)
    config = module.v1_config(
        base_url="https://opencode.ai/zen/go/v1",
        auth="proxy",
        token_budget=150_000,
        sandbox="docker",
    )
    assert config.model.provider == "opencode-go" and config.model.model == "deepseek-v4.1-flash"
    assert config.model.options["auth"] == "proxy" and config.model.api_key_env is None
    assert config.retry.llm_max_attempts == 1 and config.retry.evaluation_retries == 0
    assert config.limits.max_total_tokens == 150_000
    assert (config.sandbox.image, config.sandbox.network) == ("python:3.12", "none")
