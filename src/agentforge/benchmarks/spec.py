"""Benchmark suite specification (YAML/JSON)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentforge.core.errors import BenchmarkError
from agentforge.evaluation.base import EvaluatorSpec

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskSetup(_Strict):
    """Initial state of the task workspace."""

    files: dict[str, str] = Field(default_factory=dict, description="path -> file content")
    commands: list[str] = Field(
        default_factory=list, description="Shell commands run in the sandbox before the agent."
    )
    git_init: bool = Field(default=False, description="Initialise a git repo and commit setup.")


class BenchmarkTask(_Strict):
    id: str
    goal: str = Field(min_length=1)
    description: str = ""
    setup: TaskSetup = Field(default_factory=TaskSetup)
    allowed_tools: list[str] | None = Field(
        default=None,
        description="If set, replaces the agent's tools so every agent gets the same environment.",
    )
    expected_behavior: str = Field(default="", description="Human-readable intent of the task.")
    evaluators: list[EvaluatorSpec] = Field(
        min_length=1, description="Success criteria / evaluation rules."
    )
    timeout_seconds: float | None = Field(default=None, gt=0)
    max_steps: int | None = Field(default=None, ge=1)
    tags: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not _ID_RE.match(value):
            raise ValueError("task id must be lowercase letters, digits, '.', '_' or '-'")
        return value


class TaskDefaults(_Strict):
    timeout_seconds: float = Field(default=300.0, gt=0)
    max_steps: int = Field(default=20, ge=1)


class BenchmarkSuite(_Strict):
    id: str
    name: str
    description: str = ""
    version: str = "1"
    repeats: int = Field(default=1, ge=1, le=100)
    defaults: TaskDefaults = Field(default_factory=TaskDefaults)
    tasks: list[BenchmarkTask] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not _ID_RE.match(value):
            raise ValueError("suite id must be lowercase letters, digits, '.', '_' or '-'")
        return value

    @model_validator(mode="after")
    def _unique_task_ids(self) -> BenchmarkSuite:
        ids = [t.id for t in self.tasks]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate task ids: {sorted(duplicates)}")
        return self

    def task(self, task_id: str) -> BenchmarkTask:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise BenchmarkError(f"suite '{self.id}' has no task '{task_id}'")


def load_suite(path: str | Path) -> BenchmarkSuite:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise BenchmarkError(f"cannot read benchmark suite {path}: {exc}") from exc
    try:
        return BenchmarkSuite.model_validate(data)
    except ValueError as exc:
        raise BenchmarkError(f"invalid benchmark suite {path}: {exc}") from exc


def discover_suites(directory: str | Path) -> dict[str, tuple[Path, BenchmarkSuite]]:
    """Load every ``*.yaml``/``*.yml`` suite in a directory, keyed by suite id."""
    found: dict[str, tuple[Path, BenchmarkSuite]] = {}
    root = Path(directory)
    if not root.is_dir():
        return found
    for path in sorted([*root.glob("*.yaml"), *root.glob("*.yml")]):
        suite = load_suite(path)
        found[suite.id] = (path, suite)
    return found
