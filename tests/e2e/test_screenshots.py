"""The screenshot tooling (scripts/screenshots.py + .cjs) stays in sync with the docs.

Capturing needs a browser and is not run here; these tests cover the offline
parts: the demo data, the approval demo run and the list of pictures.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentforge.api.app import create_app
from agentforge.settings import Settings

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "docs" / "screenshots"
API = "/api/v1"


@pytest.fixture(scope="module")
def shots() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "af_screenshots", ROOT / "scripts" / "screenshots.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["af_screenshots"] = module
    spec.loader.exec_module(module)
    return module


def cli_json(shots: ModuleType, data_dir: Path, *argv: str) -> Any:
    done = subprocess.run(
        [*shots.CLI, *argv],
        cwd=ROOT,
        env=shots.child_env(data_dir),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout[done.stdout.index("{") :])


def captured_files() -> set[str]:
    script = (ROOT / "scripts" / "screenshots.cjs").read_text()
    return set(re.findall(r'file: "([\w.-]+\.png)"', script))


def test_seed_creates_the_demo_data_the_pictures_need(shots: ModuleType, tmp_path: Path) -> None:
    data = tmp_path / "demo"
    shots.seed(data)
    assert (data / "agentforge.db").is_file()

    history = cli_json(shots, data, "improve", "history", "dogfood-demo-coder", "--json")
    assert sorted(b["agent_version"] for b in history["benchmarks"]) == [1, 2]
    assert len(history["improvements"]) == 1
    # The starter benchmark and the experiment's runs are stored too.
    listed = subprocess.run(
        [*shots.CLI, "runs", "list", "-n", "100"],
        cwd=ROOT,
        env=shots.child_env(data),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "scripted-demo" in listed
    assert "test_calc" in listed


def test_seed_reports_a_failing_step(
    shots: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shots, "SEED_COMMANDS", [["bench", "run", "no-such-suite.yaml", "-a", "x"]])
    with pytest.raises(RuntimeError, match="seed step failed"):
        shots.seed(tmp_path / "demo")


def test_child_env_isolates_the_demo_from_the_callers_database(
    shots: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTFORGE_DATABASE_URL", "postgresql+asyncpg://u:p@db/prod")
    monkeypatch.setenv("AGENTFORGE_API_KEY", "k")
    env = shots.child_env(tmp_path)
    assert "AGENTFORGE_DATABASE_URL" not in env
    assert "AGENTFORGE_API_KEY" not in env
    assert env["AGENTFORGE_DATA_DIR"] == str(tmp_path)
    assert os.environ["AGENTFORGE_DATABASE_URL"].endswith("/prod")  # caller untouched


def test_approval_demo_run_pauses_at_the_gate(shots: ModuleType, settings: Settings) -> None:
    request = shots.approval_run_request()
    assert request["config"]["model"]["provider"] == "scripted"
    with TestClient(create_app(settings)) as client:
        run_id = client.post(f"{API}/runs", json=request).json()["id"]
        deadline = time.monotonic() + 20
        status = ""
        while time.monotonic() < deadline and status != "awaiting_approval":
            status = client.get(f"{API}/runs/{run_id}").json()["status"]
            time.sleep(0.05)
        assert status == "awaiting_approval"
        pending = client.get(f"{API}/runs/{run_id}/approvals").json()
        assert [(p["tool"], p["permissions"]) for p in pending] == [("write_file", ["fs:write"])]
        assert client.post(f"{API}/runs/{run_id}/cancel").json()["status"] == "cancelled"


def test_committed_screenshots_are_exactly_the_captured_ones() -> None:
    files = captured_files()
    assert len(files) >= 8
    assert {p.name for p in SHOTS.glob("*.png")} == files


def test_every_screenshot_is_shown_in_the_docs() -> None:
    docs = "\n".join(
        path.read_text() for path in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    )
    for name in sorted(captured_files()):
        assert f"screenshots/{name}" in docs, f"{name} is captured but never shown"
    for linked in set(re.findall(r"screenshots/([\w.-]+\.png)", docs)):
        assert (SHOTS / linked).is_file(), f"docs link a missing screenshot: {linked}"


# -- the recorded walk-through (scripts/screenshots.py --record) ---------------------


def test_recording_is_committed_as_a_small_animated_gif(shots: ModuleType) -> None:
    data = (SHOTS / shots.RECORDING).read_bytes()
    assert data[:6] == b"GIF89a"
    width, height = int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    assert (width, height) == (960, 540)
    assert b"NETSCAPE2.0" in data[:2048], "the GIF should loop"
    assert len(data) < 4_000_000, "keep the recording small enough for the README"


def test_recording_is_shown_in_the_docs_as_offline_data(shots: ModuleType) -> None:
    for page in (ROOT / "README.md", ROOT / "docs" / "tour.md"):
        text = page.read_text()
        position = text.index(f"screenshots/{shots.RECORDING}")
        assert "OFFLINE" in text[position : position + 600], f"{page.name}: label the recording"


def test_gif_command_trims_the_warm_up_and_writes_the_target(
    shots: ModuleType, tmp_path: Path
) -> None:
    command = shots.gif_command("ffmpeg", tmp_path / "tour.webm", 3.456, tmp_path / "tour.gif")
    assert command[0] == "ffmpeg"
    assert command[command.index("-ss") + 1] == "3.46"
    assert command.index("-ss") < command.index("-i"), "trim while seeking the input"
    assert command[command.index("-i") + 1] == str(tmp_path / "tour.webm")
    assert command[-1] == str(tmp_path / "tour.gif")
    assert "scale=960" in command[command.index("-filter_complex") + 1]
    negative = shots.gif_command("ffmpeg", tmp_path / "a", -1.0, tmp_path / "b")
    assert negative[negative.index("-ss") + 1] == "0.00"


def test_record_needs_ffmpeg(
    shots: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shots.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="ffmpeg is required"):
        shots.record(tmp_path, tmp_path / "out")
    assert shots.main(["--record", "--out", str(tmp_path / "out")]) == 1
    assert not (tmp_path / "out").exists()


def test_recording_script_follows_labels_the_dashboard_has() -> None:
    """The walk-through clicks by visible text; a renamed label must fail here, not later."""
    script = (ROOT / "scripts" / "recording.cjs").read_text()
    web = "\n".join(
        path.read_text()
        for folder in ("app", "components")
        for path in sorted((ROOT / "web" / folder).rglob("*.tsx"))
    )
    labels = set(re.findall(r'getBy(?:Text|Role)\((?:"\w+", \{ name: )?"([^"]+)"', script))
    assert labels >= {"Improvement", "Runs", "Approve", "Pending approval", "Succeeded"}
    for label in sorted(labels):
        assert label in web, f"recording.cjs waits for {label!r}, which the dashboard lacks"
    tour = (ROOT / "scripts" / "tour.py").read_text()
    agent = re.search(r'TOUR_AGENT = "([\w-]+)"', script)
    assert agent is not None and f'AGENT_NAME = "{agent.group(1)}"' in tour


def test_improvement_history_fits_its_card() -> None:
    """Regression: the table had six columns and clipped "Δ pass rate" at 1440 px."""
    page = (ROOT / "web" / "app" / "improvement" / "page.tsx").read_text()
    history = page[page.index('title="Improvement history"') : page.index('title="Experiment')]
    assert re.findall(r"<TH[^>]*>([^<]+)</TH>", history) == [
        "Agent",
        "Versions",
        "Status",
        "Verdict",
        "Δ pass rate",
    ]
    assert "relativeTime(c.created_at)" in history, "the cycle's age moved under the agent name"
    assert "2xl:grid-cols-2" in page and "xl:grid-cols-2" not in page.replace("2xl:", "")
