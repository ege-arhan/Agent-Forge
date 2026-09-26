"""End-to-end CLI tests (offline, scripted demo agent)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from agentforge.cli import main
from agentforge.settings import get_settings

pytestmark = pytest.mark.e2e

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
DEMO = str(EXAMPLES / "agents" / "scripted-demo.yaml")


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTFORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("AGENTFORGE_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_run_command_success_and_persistence(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "run",
            DEMO,
            "-q",
            "--goal",
            "Create a file named hello.txt containing exactly the text: Hello, AgentForge!",
            "--eval",
            '{"type": "file_contains", "path": "hello.txt", "text": "Hello, AgentForge!"}',
        ]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "status:     succeeded" in out and "evaluation: PASSED" in out

    assert main(["runs", "list"]) == 0
    listing = capsys.readouterr().out
    assert "succeeded" in listing and "(1 of 1)" in listing
    run_id = listing.split()[0]
    assert main(["runs", "show", run_id, "--json"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["id"] == run_id and record["evaluation"]["passed"] is True


def test_run_failing_evaluation_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "run",
            DEMO,
            "-q",
            "--no-db",
            "--goal",
            "unknown goal",
            "--eval",
            '{"type": "file_exists", "path": "nothing.txt"}',
        ]
    )
    assert code == 1
    assert "evaluation: FAILED" in capsys.readouterr().out


def test_bench_and_experiment_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bench", "list", str(EXAMPLES / "benchmarks")]) == 0
    assert "starter" in capsys.readouterr().out
    code = main(
        [
            "bench",
            "run",
            str(EXAMPLES / "benchmarks" / "starter.yaml"),
            "-a",
            DEMO,
            "-t",
            "create-greeting",
            "-t",
            "count-csv-rows",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0 and "pass rate 100.00%" in out
    code = main(["experiment", "run", str(EXAMPLES / "experiments" / "step-budget.yaml"), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert {row["variant"] for row in data["comparison"]} == {"baseline", "max-steps-2"}


def test_agents_tools_providers(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["agents", "create", DEMO]) == 0
    assert main(["agents", "create", DEMO]) == 0  # identical config: no new version
    assert main(["agents", "list"]) == 0
    assert "v1" in capsys.readouterr().out
    changed = tmp_path / "demo.yaml"
    data = yaml.safe_load(Path(DEMO).read_text())
    changed.write_text(yaml.safe_dump({**data, "description": "changed"}))
    assert main(["agents", "create", str(changed)]) == 0  # changed config: new version
    assert main(["agents", "list"]) == 0
    assert "v2" in capsys.readouterr().out
    assert main(["tools"]) == 0
    assert "run_command" in capsys.readouterr().out
    assert main(["providers"]) == 0
    assert "anthropic" in capsys.readouterr().out


def test_config_error_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: bad\nmodel: {provider: scripted}\ntools: [nope]\n")
    assert main(["run", str(bad), "--goal", "x", "--no-db"]) == 2
    assert "unknown tool" in capsys.readouterr().err


def test_db_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["db", "current"]) == 0
    assert "none" in capsys.readouterr().out
    assert main(["db", "upgrade"]) == 0
    assert "database at revision" in capsys.readouterr().out
    assert main(["db", "current"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_database_url_credentials_are_masked() -> None:
    from agentforge.cli import _safe_url

    assert (
        _safe_url("postgresql+asyncpg://user:p@ss@db:5432/x")
        == "postgresql+asyncpg://user:***@db:5432/x"
    )
    assert _safe_url("sqlite+aiosqlite:////tmp/a.db") == "sqlite+aiosqlite:////tmp/a.db"


DOGFOOD = Path(__file__).resolve().parents[2] / "dogfood"
DEMO_V1 = str(DOGFOOD / "agents" / "offline" / "demo-coder-v1.yaml")
CODING = str(DOGFOOD / "benchmarks" / "coding.yaml")


def _history(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    capsys.readouterr()
    assert main(["improve", "history", "dogfood-demo-coder", "--json"]) == 0
    data: dict[str, Any] = json.loads(capsys.readouterr().out)
    return data


def test_improvement_loop_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    results = tmp_path / "results"
    code = main(
        ["bench", "run", CODING, "-a", DEMO_V1, "-r", "2", "--save-agent", "--report", str(results)]
    )
    assert code == 0
    out = capsys.readouterr()
    assert "results=OFFLINE" in out.out and "dogfood-demo-coder v1" in out.err
    [report] = (results / "offline" / "dogfood-coding-v1").glob("*.json")
    assert json.loads(report.read_text())["summary"]["passed"] == 0
    assert report.with_suffix(".md").exists()
    assert not (results / "real").exists()

    baseline = _history(capsys)["benchmarks"][0]["id"]
    assert main(["improve", "analyze", baseline]) == 0
    assert "step_limit" in capsys.readouterr().out

    assert main(["improve", "propose", baseline, "--json"]) == 0
    cycle = json.loads(capsys.readouterr().out)
    assert cycle["proposal"]["changes"][0]["path"] == "limits.max_steps"
    assert main(["improve", "apply", cycle["id"]]) == 0
    assert "v1 -> v2" in capsys.readouterr().out
    assert main(["improve", "evaluate", cycle["id"]]) == 0
    assert "verdict: IMPROVED" in capsys.readouterr().out

    history = _history(capsys)
    assert [v["version"] for v in history["versions"]] == [2, 1]
    assert history["improvements"][0]["status"] == "evaluated"
    candidate = history["improvements"][0]["candidate_benchmark_run_id"]

    assert main(["bench", "compare", baseline, candidate]) == 0
    assert "verdict: IMPROVED" in capsys.readouterr().out
    assert main(["bench", "report", candidate]) == 0
    assert "OFFLINE / SCRIPTED PROVIDER" in capsys.readouterr().out
    assert main(["improve", "history", "dogfood-demo-coder"]) == 0
    assert "improvement limits.max_steps: 3 -> 20" in capsys.readouterr().out

    # A second loop from the improved version has nothing left to propose.
    assert main(["improve", "run", candidate]) == 0
    assert "proposal: no changes" in capsys.readouterr().out
    assert main(["improve", "reject", cycle["id"], "--reason", "demo"]) == 0
    assert "reverted: baseline config stored as v3" in capsys.readouterr().out


def test_bench_run_report_needs_database(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bench", "run", CODING, "-a", DEMO_V1, "--no-db", "--save-agent"]) == 2
    assert "need the database" in capsys.readouterr().err


def test_dogfood_script(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "dogfood_script", Path(__file__).resolve().parents[2] / "scripts" / "dogfood.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)  # dataclasses need the module registered
    spec.loader.exec_module(module)

    results = tmp_path / "results"
    assert module.main(["--results", str(results), "--roles", "debugging", "offline"]) == 0
    out = capsys.readouterr().out
    assert "[OFFLINE] dogfood-debugging@1" in out
    assert "verdict: IMPROVED" in out  # the improvement-loop demo
    assert len(list((results / "offline" / "dogfood-debugging-v1").glob("*.json"))) == 1
    assert len(list((results / "offline" / "improvement-demo").glob("*.json"))) == 1
    assert not (results / "real").exists()

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert module.main(["--results", str(results), "real", "--provider", "anthropic"]) == 0
    assert "not run — ANTHROPIC_API_KEY is not set" in capsys.readouterr().out
    assert not (results / "real").exists()
    assert module.main(["--results", str(results), "real", "--provider", "local"]) == 0
    assert "needs --base-url" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="unknown role"):
        module.main(["--roles", "nope", "offline"])

    config = module.real_config(
        DOGFOOD / "agents" / "coding.yaml",
        provider="openai",
        model="gpt-x",
        base_url=None,
        sandbox="local",
    )
    assert (config.model.provider, config.model.model) == ("openai", "gpt-x")
    assert config.sandbox.kind.value == "local"  # validated into the enum
    kept = module.real_config(
        DOGFOOD / "agents" / "coding.yaml",
        provider="anthropic",
        model=None,
        base_url=None,
        sandbox="docker",
    )
    assert kept.model.model == "claude-sonnet-5" and kept.sandbox.kind.value == "docker"
