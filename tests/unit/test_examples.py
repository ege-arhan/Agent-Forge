"""Every shipped example must stay valid."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge.benchmarks import load_suite
from agentforge.config_files import load_agent_config
from agentforge.experiments import load_experiment, variant_config
from agentforge.tools.registry import default_registry

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.mark.parametrize("path", sorted((EXAMPLES / "agents").glob("*.yaml")), ids=lambda p: p.name)
def test_example_agents_are_valid(path: Path) -> None:
    config = load_agent_config(path)
    default_registry().resolve(config.tools)  # every tool/toolset exists
    if config.model.provider != "local" and config.sandbox.kind.value == "docker":
        assert config.sandbox.image == "agentforge-sandbox:latest"


@pytest.mark.parametrize(
    "path", sorted((EXAMPLES / "benchmarks").glob("*.yaml")), ids=lambda p: p.name
)
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
