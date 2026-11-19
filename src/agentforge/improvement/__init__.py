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
from agentforge.improvement.diagnosis import (
    SIGNAL_DESCRIPTIONS,
    STAGE_DESCRIPTIONS,
    FailureStage,
    ToolPhase,
    TraceDiagnosis,
    TraceSignal,
    diagnose_run,
)
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
    "SIGNAL_DESCRIPTIONS",
    "STAGE_DESCRIPTIONS",
    "BenchmarkComparison",
    "ChangeOperation",
    "CycleStatus",
    "FailureAnalysis",
    "FailureCategory",
    "FailureStage",
    "ImprovementCycle",
    "ImprovementProposal",
    "ProposedChange",
    "TaskFailure",
    "ToolPhase",
    "TraceDiagnosis",
    "TraceSignal",
    "Verdict",
    "analyze",
    "apply_changes",
    "classify_run",
    "compare_benchmarks",
    "diagnose_run",
    "prepare_manual",
    "propose",
]
