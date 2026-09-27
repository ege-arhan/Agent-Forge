"""Run records, evaluation results and metrics.

These models are the canonical, provider-neutral record of what an agent did.
They are persisted by the storage layer, served by the API and consumed by the
evaluation and benchmark engines.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agentforge.core.config import AgentConfig
from agentforge.core.ids import new_id, utcnow


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL


_TERMINAL = frozenset(
    {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT}
)


class StepKind(StrEnum):
    PLAN = "plan"
    ACTION = "action"  # one model turn plus the tool calls it requested
    EVALUATION = "evaluation"


class ToolCallStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    DENIED = "denied"
    TIMEOUT = "timeout"
    INVALID_INPUT = "invalid_input"


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: TokenUsage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens


class ErrorInfo(BaseModel):
    type: str
    message: str
    retryable: bool = False


class LLMCallRecord(BaseModel):
    provider: str
    model: str
    started_at: datetime
    finished_at: datetime
    latency_ms: int
    attempts: int = 1
    stop_reason: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    cost_usd: float | None = None
    error: ErrorInfo | None = None


class ToolCallRecord(BaseModel):
    id: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: ToolCallStatus
    output: str = ""
    error: str | None = None
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    truncated: bool = False


class Step(BaseModel):
    index: int
    kind: StepKind
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    thought: str = Field(default="", description="Assistant text produced in this step.")
    llm_call: LLMCallRecord | None = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    plan: list[str] | None = None
    evaluation: EvaluationResult | None = None
    error: ErrorInfo | None = None


class EvaluatorResult(BaseModel):
    """Outcome of a single evaluator."""

    name: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    weight: float = Field(default=1.0, ge=0.0)
    required: bool = True
    details: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    """Aggregate of evaluator results for a run."""

    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    results: list[EvaluatorResult] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=utcnow)

    def feedback(self) -> str:
        failed = [r for r in self.results if not r.passed]
        if not failed:
            return "All checks passed."
        return "\n".join(f"- {r.name}: {r.details or 'failed'}" for r in failed)


class RunMetrics(BaseModel):
    """Objective measurements derived from a run record (never estimated)."""

    duration_seconds: float | None = None
    steps: int = 0
    llm_calls: int = 0
    llm_retries: int = 0
    evaluation_retries: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    tool_success_rate: float | None = None
    errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = Field(
        default=None, description="Only set when every LLM call had known pricing."
    )


class Agent(BaseModel):
    """A stored, versioned agent definition."""

    id: str = Field(default_factory=lambda: new_id("agt"))
    config: AgentConfig
    version: int = 1
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def name(self) -> str:
        return self.config.name


class AgentVersionSource(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    IMPROVEMENT = "improvement"
    REVERT = "revert"


class AgentVersion(BaseModel):
    """Immutable snapshot of a stored agent's configuration at one version."""

    agent_id: str
    version: int = Field(ge=1)
    config: AgentConfig
    source: AgentVersionSource = AgentVersionSource.CREATED
    change_summary: str = ""
    improvement_id: str | None = Field(
        default=None, description="Improvement cycle that produced this version, if any."
    )
    parent_version: int | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Run(BaseModel):
    id: str = Field(default_factory=lambda: new_id("run"))
    agent_id: str | None = None
    agent_name: str
    config: AgentConfig
    goal: str
    status: RunStatus = RunStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    steps: list[Step] = Field(default_factory=list)
    plan: list[str] | None = None
    result: str | None = None
    error: ErrorInfo | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    evaluation: EvaluationResult | None = None
    metrics: RunMetrics = Field(default_factory=RunMetrics)
    workspace: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    parent_run_id: str | None = Field(
        default=None, description="Set when this run reproduces or retries another run."
    )
    evaluators: list[dict[str, Any]] = Field(
        default_factory=list, description="Evaluator specs used, stored for reproducibility."
    )

    @property
    def tool_calls(self) -> list[ToolCallRecord]:
        return [call for step in self.steps for call in step.tool_calls]


Step.model_rebuild()
