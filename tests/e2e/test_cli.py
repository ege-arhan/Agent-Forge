"""End-to-end CLI tests (offline, scripted demo agent)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def test_agents_tools_providers(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["agents", "create", DEMO]) == 0
    assert main(["agents", "create", DEMO]) == 0  # second call updates
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
