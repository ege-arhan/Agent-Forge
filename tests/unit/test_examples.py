"""Every shipped example must stay valid."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge.benchmarks import load_suite
from agentforge.benchmarks.spec import discover_suites
from agentforge.config_files import load_agent_config
from agentforge.core.errors import BenchmarkError
from agentforge.experiments import load_experiment, variant_config
from agentforge.settings import Settings
from agentforge.tools.registry import default_registry

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
DOGFOOD = ROOT / "dogfood"
AGENT_FILES = sorted(
    [
        *(EXAMPLES / "agents").glob("*.yaml"),
        *(DOGFOOD / "agents").glob("*.yaml"),
        *(DOGFOOD / "agents" / "offline").glob("*.yaml"),
    ]
)
SUITE_FILES = sorted(
    [*(EXAMPLES / "benchmarks").glob("*.yaml"), *(DOGFOOD / "benchmarks").glob("*.yaml")]
)


@pytest.mark.parametrize("path", AGENT_FILES, ids=lambda p: p.name)
def test_example_agents_are_valid(path: Path) -> None:
    config = load_agent_config(path)
    default_registry().resolve(config.tools)  # every tool/toolset exists
    if config.model.provider != "local" and config.sandbox.kind.value == "docker":
        assert config.sandbox.image == "agentforge-sandbox:latest"


@pytest.mark.parametrize("path", SUITE_FILES, ids=lambda p: p.name)
def test_example_suites_are_valid(path: Path) -> None:
    suite = load_suite(path)
    for task in suite.tasks:
        if task.allowed_tools:
            default_registry().resolve(task.allowed_tools)


@pytest.mark.parametrize(
    "path", sorted((EXAMPLES / "experiments").glob("*.yaml")), ids=lambda p: p.name
)
def test_example_experiments_are_valid(path: Path) -> None:
    spec, _, base = load_experiment(path)
    for variant in spec.variants:
        variant_config(base, variant)


def test_default_settings_discover_examples_and_dogfood(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("AGENTFORGE_BENCHMARKS_DIR", raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.benchmark_dirs == [Path("examples/benchmarks"), Path("dogfood/benchmarks")]
    suites = discover_suites(settings.benchmark_dirs)
    assert {"starter", "dogfood-coding", "dogfood-issues"} <= set(suites)
    assert Settings(benchmarks_dir=Path("x"), _env_file=None).benchmark_dirs == [Path("x")]  # type: ignore[call-arg]


def test_duplicate_suite_ids_across_directories_are_rejected(tmp_path: Path) -> None:
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "s.yaml").write_text(
            (EXAMPLES / "benchmarks" / "starter.yaml").read_text()
        )
    with pytest.raises(BenchmarkError, match="duplicate benchmark suite id"):
        discover_suites([tmp_path / "a", tmp_path / "b"])
