"""The offline tour (scripts/tour.py, docs/tour.md) runs and stays in sync with its docs.

No model is called: the tour uses the scripted dogfood agents only.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from agentforge.settings import get_settings

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]


def load_tour() -> ModuleType:
    spec = importlib.util.spec_from_file_location("af_tour", ROOT / "scripts" / "tour.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["af_tour"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tour() -> ModuleType:
    return load_tour()


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("AGENTFORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("AGENTFORGE_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_every_step_behaves_as_documented(tour: ModuleType) -> None:
    lines: list[str] = []
    runner = tour.Tour(out=lines.append)
    assert runner.run(), "\n".join(lines)
    exits = [(o.step.title, o.exit_code) for o in runner.outcomes]
    assert [code for _, code in exits] == [0, 0, 0, 0, 0, 1, 1], exits
    text = "\n".join(lines)
    assert "[step_limit]" in text
    assert "limits.max_steps set 20" in text
    assert "REGRESSION GATE: PASS (exit 0)" in text
    assert text.count("REGRESSION GATE: REGRESSION (exit 1)") == 2


def test_an_unexpected_exit_code_fails_the_tour(
    tour: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tour.run_cli

    def gate_always_passes(argv: list[str]) -> tuple[int, str]:
        code, out = real(argv)
        return (0, out) if argv[:2] == ["bench", "gate"] else (code, out)

    monkeypatch.setattr(tour, "run_cli", gate_always_passes)
    runner = tour.Tour(out=lambda _: None)
    assert not runner.run()
    assert [o.ok for o in runner.outcomes][-2:] == [False, False]


def test_main_keeps_the_data_directory(
    tour: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    keep = tmp_path / "kept"
    assert tour.main(["--keep", str(keep)]) == 0
    out = capsys.readouterr().out
    assert "tour complete" in out
    assert "agentforge serve" in out
    assert (keep / "agentforge.db").is_file()


def test_docs_show_the_commands_the_tour_runs(tour: ModuleType) -> None:
    doc = (ROOT / "docs" / "tour.md").read_text()
    for path in (tour.SUITE, tour.DEMO_AGENT, tour.BASELINE):
        assert (ROOT / path).is_file(), path
        assert path in doc, path
    for fragment in (
        "scripts/tour.py",
        "agentforge improve analyze",
        "agentforge improve run",
        "agentforge improve history dogfood-demo-coder",
        "agentforge bench gate",
        "OFFLINE",
    ):
        assert fragment in doc, fragment
