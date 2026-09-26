"""Evaluator interface, specs and aggregation."""

from __future__ import annotations

import importlib
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from agentforge.core.errors import ConfigurationError
from agentforge.core.models import EvaluationResult, EvaluatorResult, Run
from agentforge.sandbox.base import Sandbox
from agentforge.sandbox.workspace import Workspace

logger = logging.getLogger("agentforge.evaluation")


class EvaluatorSpec(BaseModel):
    """Declarative evaluator reference, e.g. ``{type: file_contains, path: a.txt, text: hi}``.

    Unknown keys are passed to the evaluator as parameters.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    name: str | None = None
    weight: float = Field(default=1.0, ge=0.0)
    required: bool = True

    @property
    def params(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class NoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class EvaluationContext:
    run: Run
    workspace: Workspace | None = None
    sandbox: Sandbox | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class Verdict:
    passed: bool
    score: float | None = None
    details: str = ""
    metrics: dict[str, float] = field(default_factory=dict)


class Evaluator(ABC):
    """Base class for evaluators.

    Subclasses define a Pydantic ``Params`` model for their parameters and
    implement :meth:`check`. Scores are in ``[0, 1]``; when ``check`` returns
    no explicit score it is 1.0 for pass and 0.0 for fail.
    """

    type_name: ClassVar[str]
    description: ClassVar[str] = ""

    Params: ClassVar[type[BaseModel]] = NoParams

    def __init__(self, params: dict[str, Any]) -> None:
        self.params: Any
        try:
            self.params = self.Params.model_validate(params)
        except ValueError as exc:
            raise ConfigurationError(
                f"invalid parameters for evaluator '{self.type_name}': {exc}"
            ) from exc

    @abstractmethod
    async def check(self, ctx: EvaluationContext) -> Verdict: ...


EvaluatorFactory = Callable[[dict[str, Any]], Evaluator]
_REGISTRY: dict[str, type[Evaluator]] = {}
_plugins_loaded = False


def register_evaluator(cls: type[Evaluator]) -> type[Evaluator]:
    _REGISTRY[cls.type_name] = cls
    return cls


def _load_plugins() -> None:
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    import agentforge.evaluation.builtin  # noqa: F401 - registers built-ins

    for ep in entry_points(group="agentforge.evaluators"):
        cls = ep.load()
        if isinstance(cls, type) and issubclass(cls, Evaluator):
            _REGISTRY.setdefault(cls.type_name, cls)


def available_evaluators() -> dict[str, type[Evaluator]]:
    _load_plugins()
    return dict(sorted(_REGISTRY.items()))


def build_evaluator(spec: EvaluatorSpec) -> Evaluator:
    _load_plugins()
    if spec.type == "python":
        # {type: python, class: "package.module:ClassName", ...params}
        target = spec.params.get("class")
        if not isinstance(target, str) or ":" not in target:
            raise ConfigurationError("python evaluator requires class: 'module:ClassName'")
        module_name, _, attr = target.partition(":")
        cls = getattr(importlib.import_module(module_name), attr, None)
        if not (isinstance(cls, type) and issubclass(cls, Evaluator)):
            raise ConfigurationError(f"'{target}' is not an Evaluator subclass")
        params = {k: v for k, v in spec.params.items() if k != "class"}
        return cls(params)
    cls = _REGISTRY.get(spec.type)
    if cls is None:
        raise ConfigurationError(
            f"unknown evaluator type '{spec.type}' (known: {', '.join(sorted(_REGISTRY))})"
        )
    return cls(spec.params)


async def evaluate(specs: list[EvaluatorSpec], ctx: EvaluationContext) -> EvaluationResult | None:
    """Run all evaluators and aggregate. Returns ``None`` when there are none."""
    if not specs:
        return None
    results: list[EvaluatorResult] = []
    for spec in specs:
        name = spec.name or spec.type
        try:
            evaluator = build_evaluator(spec)
            verdict = await evaluator.check(ctx)
            score = verdict.score if verdict.score is not None else float(verdict.passed)
            results.append(
                EvaluatorResult(
                    name=name,
                    passed=verdict.passed,
                    score=min(1.0, max(0.0, score)),
                    weight=spec.weight,
                    required=spec.required,
                    details=verdict.details,
                    metrics=verdict.metrics,
                )
            )
        except ConfigurationError:
            raise
        except Exception as exc:
            logger.warning("evaluator %s failed: %s", name, exc)
            results.append(
                EvaluatorResult(
                    name=name,
                    passed=False,
                    score=0.0,
                    weight=spec.weight,
                    required=spec.required,
                    details=f"evaluator error: {type(exc).__name__}: {exc}",
                )
            )
    return aggregate(results)


def aggregate(results: list[EvaluatorResult]) -> EvaluationResult:
    total_weight = sum(r.weight for r in results)
    score = sum(r.score * r.weight for r in results) / total_weight if total_weight > 0 else 0.0
    passed = all(r.passed for r in results if r.required)
    return EvaluationResult(passed=passed, score=round(score, 4), results=results)
