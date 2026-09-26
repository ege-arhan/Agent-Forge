"""Evaluation engine: evaluators, aggregation and run metrics."""

from agentforge.evaluation.base import (
    EvaluationContext,
    Evaluator,
    EvaluatorSpec,
    Verdict,
    aggregate,
    available_evaluators,
    build_evaluator,
    evaluate,
    register_evaluator,
)
from agentforge.evaluation.metrics import compute_metrics

__all__ = [
    "EvaluationContext",
    "Evaluator",
    "EvaluatorSpec",
    "Verdict",
    "aggregate",
    "available_evaluators",
    "build_evaluator",
    "compute_metrics",
    "evaluate",
    "register_evaluator",
]
