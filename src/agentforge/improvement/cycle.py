"""Improvement cycle record: benchmark → analysis → proposal → new version → compare."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from agentforge.benchmarks.runner import ResultClass
from agentforge.core.ids import new_id, utcnow
from agentforge.improvement.analysis import FailureAnalysis
from agentforge.improvement.comparison import BenchmarkComparison
from agentforge.improvement.proposal import ImprovementProposal


class CycleStatus(StrEnum):
    PROPOSED = "proposed"  # analysis + proposal recorded, nothing changed yet
    APPLIED = "applied"  # a new agent version was created from the proposal
    EVALUATING = "evaluating"  # the new version is being benchmarked
    EVALUATED = "evaluated"  # candidate benchmark finished and compared
    REJECTED = "rejected"  # proposal declined, or the new version was reverted
    FAILED = "failed"  # the evaluation could not complete


class ImprovementCycle(BaseModel):
    id: str = Field(default_factory=lambda: new_id("imp"))
    agent_id: str
    agent_name: str
    status: CycleStatus = CycleStatus.PROPOSED
    suite_id: str
    suite_version: str
    result_class: ResultClass
    task_ids: list[str] = Field(default_factory=list)
    repeats: int = 1
    from_version: int
    to_version: int | None = None
    reverted_to_version: int | None = None
    baseline_benchmark_run_id: str
    candidate_benchmark_run_id: str | None = None
    analysis: FailureAnalysis
    proposal: ImprovementProposal
    applied_change_ids: list[str] = Field(default_factory=list)
    comparison: BenchmarkComparison | None = None
    notes: str = ""
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
