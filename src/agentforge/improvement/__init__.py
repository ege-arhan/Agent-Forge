"""Agent improvement loop.

Agent version → benchmark → evaluation → failure analysis → improvement
proposal → new agent version → benchmark again → compare. Every step is
persisted, so the full history of an agent's improvement is preserved.

The storage-backed orchestration lives in :mod:`agentforge.improvement.loop`.
"""

from __future__ import annotations

from agentforge.improvement.analysis import (
    CATEGORY_DESCRIPTIONS,
    FailureAnalysis,
    FailureCategory,
    TaskFailure,
    analyze,
    classify_run,
)
from agentforge.improvement.comparison import BenchmarkComparison, Verdict, compare_benchmarks
from agentforge.improvement.cycle import CycleStatus, ImprovementCycle
from agentforge.improvement.proposal import (
    ALLOWED_PATHS,
    ChangeOperation,
    ImprovementProposal,
    ProposedChange,
    apply_changes,
    prepare_manual,
    propose,
)

__all__ = [
    "ALLOWED_PATHS",
    "CATEGORY_DESCRIPTIONS",
    "BenchmarkComparison",
    "ChangeOperation",
    "CycleStatus",
    "FailureAnalysis",
    "FailureCategory",
    "ImprovementCycle",
    "ImprovementProposal",
    "ProposedChange",
    "TaskFailure",
    "Verdict",
    "analyze",
    "apply_changes",
    "classify_run",
    "compare_benchmarks",
    "prepare_manual",
    "propose",
]
