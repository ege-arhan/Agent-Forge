"""`agentforge bench gate` end to end, with the offline (scripted) dogfood agents.

The baseline is a committed-style report file, as a CI job would use it; the
candidate is either a report file or a benchmark run stored in this job's
database. No model is called.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge.cli import main
from agentforge.settings import get_settings

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
CODING = str(ROOT / "dogfood" / "benchmarks" / "coding.yaml")
REFERENCE = str(ROOT / "dogfood" / "agents" / "offline" / "coding.yaml")  # passes 2/2
DEMO_V1 = str(ROOT / "dogfood" / "agents" / "offline" / "demo-coder-v1.yaml")  # fails 0/2


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTFORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("AGENTFORGE_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def bench(agent: str, capsys: pytest.CaptureFixture[str], report_dir: Path | None = None) -> str:
    args = ["bench", "run", CODING, "-a", agent, "--json"]
    if report_dir is not None:
        args += ["--report", str(report_dir)]
    assert main(args) == 0
    bench_id: str = json.loads(capsys.readouterr().out)["id"]
    return bench_id


@pytest.fixture
def baseline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    bench(REFERENCE, capsys, tmp_path / "baseline")
    [path] = (tmp_path / "baseline" / "offline" / "dogfood-coding-v1").glob("*.json")
    return path


def gate(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    code = main(["bench", "gate", *args])
    return code, capsys.readouterr().out


def test_no_regression_exits_0(baseline: Path, capsys: pytest.CaptureFixture[str]) -> None:
    candidate = bench(REFERENCE, capsys)
    code, out = gate(capsys, "--baseline", str(baseline), "--candidate", candidate)
    assert code == 0, out
    assert out.startswith("REGRESSION GATE: PASS (exit 0)")


def test_regression_exits_1(
    baseline: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate = bench(DEMO_V1, capsys)
    code, out = gate(
        capsys,
        "--baseline",
        str(baseline),
        "--candidate",
        candidate,
        "--output",
        str(tmp_path / "gate.json"),
    )
    assert code == 1, out
    assert "REGRESSION GATE: REGRESSION (exit 1)" in out
    assert "task implement-slugify: pass rate dropped by 1.0000" in out
    stored = json.loads((tmp_path / "gate.json").read_text())
    assert stored["verdict"] == "regression" and stored["exit_code"] == 1


def test_thresholds_from_the_command_line(
    baseline: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate = bench(DEMO_V1, capsys)
    code, out = gate(
        capsys,
        "--baseline",
        str(baseline),
        "--candidate",
        candidate,
        "--max-pass-rate-drop",
        "1",
        "--max-task-pass-rate-drop",
        "1",
        "--max-mean-score-drop",
        "1",
        "--json",
    )
    assert code == 0, out
    result = json.loads(out)
    assert result["verdict"] == "pass" and result["thresholds"]["max_pass_rate_drop"] == 1.0
    code, out = gate(
        capsys, "--baseline", str(baseline), "--candidate", candidate, "--min-pass-rate", "2"
    )
    assert code == 2 and "invalid thresholds" in out


def test_missing_baseline_is_an_explicit_error(capsys: pytest.CaptureFixture[str]) -> None:
    candidate = bench(REFERENCE, capsys)
    code, out = gate(capsys, "--baseline", "baselines/none.json", "--candidate", candidate)
    assert code == 2
    assert "baseline report file not found: baselines/none.json" in out
    code, out = gate(capsys, "--baseline", "bench_doesnotexist", "--candidate", candidate)
    assert code == 2
    assert "neither a report file nor a stored benchmark run" in out
    with pytest.raises(SystemExit) as info:  # no implicit baseline
        main(["bench", "gate", "--candidate", candidate])
    assert info.value.code == 2


def test_invalid_report_is_an_explicit_error(
    baseline: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{"suite_id": "dogfood-coding"}')
    code, out = gate(capsys, "--baseline", str(baseline), "--candidate", str(broken))
    assert code == 2 and "candidate is not a valid benchmark report" in out
    other = tmp_path / "other-suite.json"
    data = json.loads(baseline.read_text())
    data["suite_id"] = "another-suite"
    other.write_text(json.dumps(data))
    code, out = gate(capsys, "--baseline", str(baseline), "--candidate", str(other))
    assert code == 2 and "different suites" in out


def test_infrastructure_failure_is_an_explicit_error(
    baseline: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = json.loads(baseline.read_text())
    data["runs"][0].update(
        success=False, status="failed", failure_category="setup", error="setup: sandbox failed"
    )
    infra = tmp_path / "infra.json"
    infra.write_text(json.dumps(data))
    code, out = gate(capsys, "--baseline", str(baseline), "--candidate", str(infra))
    assert code == 2
    assert "failed for an infrastructure reason (setup): setup: sandbox failed" in out


def test_output_is_deterministic(baseline: Path, capsys: pytest.CaptureFixture[str]) -> None:
    candidate = bench(DEMO_V1, capsys)
    outputs = {
        gate(capsys, "--baseline", str(baseline), "--candidate", candidate) for _ in range(2)
    }
    assert len(outputs) == 1
    json_outputs = {
        gate(capsys, "--baseline", str(baseline), "--candidate", candidate, "--json")
        for _ in range(2)
    }
    assert len(json_outputs) == 1


def test_historical_report_without_new_fields_still_works(
    baseline: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = json.loads(baseline.read_text())
    data.pop("suite_digest")
    for run in data["runs"]:
        run.pop("failure_category", None)
    old = tmp_path / "old.json"
    old.write_text(json.dumps(data))
    code, out = gate(capsys, "--baseline", str(old), "--candidate", str(baseline))
    assert code == 0, out
    assert "predates suite digests" in out
