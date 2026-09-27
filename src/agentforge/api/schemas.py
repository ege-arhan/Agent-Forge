"""HTTP API request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentforge.core.config import AgentConfig
from agentforge.core.models import Agent, Run, RunStatus
from agentforge.evaluation.base import EvaluatorSpec
from agentforge.experiments import Variant
from agentforge.improvement.proposal import ProposedChange


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentOut(BaseModel):
    id: str
    name: str
    description: str
    version: int
    created_at: datetime
    updated_at: datetime
    config: AgentConfig

    @classmethod
    def of(cls, agent: Agent) -> AgentOut:
        return cls(
            id=agent.id,
            name=agent.name,
            description=agent.config.description,
            version=agent.version,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
            config=agent.config,
        )


class RunCreate(_Request):
    goal: str = Field(min_length=1, max_length=50_000)
    agent_id: str | None = None
    config: AgentConfig | None = Field(
        default=None, description="Ad-hoc agent config (instead of agent_id)."
    )
    evaluators: list[EvaluatorSpec] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _exactly_one_agent(self) -> RunCreate:
        if (self.agent_id is None) == (self.config is None):
            raise ValueError("provide exactly one of agent_id or config")
        return self


class RunSummary(BaseModel):
    id: str
    agent_id: str | None
    agent_name: str
    goal: str
    status: RunStatus
    provider: str
    model: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None
    steps: int
    tool_calls: int
    tool_success_rate: float | None
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    passed: bool | None
    score: float | None
    error_type: str | None
    labels: dict[str, str]

    @classmethod
    def of(cls, run: Run) -> RunSummary:
        m = run.metrics
        return cls(
            id=run.id,
            agent_id=run.agent_id,
            agent_name=run.agent_name,
            goal=run.goal if len(run.goal) <= 300 else run.goal[:297] + "...",
            status=run.status,
            provider=run.config.model.provider,
            model=run.config.model.model,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            duration_seconds=m.duration_seconds,
            steps=m.steps if run.status.is_terminal else len(run.steps),
            tool_calls=m.tool_calls if run.status.is_terminal else len(run.tool_calls),
            tool_success_rate=m.tool_success_rate,
            input_tokens=run.usage.input_tokens,
            output_tokens=run.usage.output_tokens,
            cost_usd=m.cost_usd,
            passed=run.evaluation.passed if run.evaluation else None,
            score=run.evaluation.score if run.evaluation else None,
            error_type=run.error.type if run.error else None,
            labels=run.labels,
        )


class RunList(BaseModel):
    items: list[RunSummary]
    total: int


class BenchmarkRunCreate(_Request):
    suite_id: str
    agent_id: str | None = None
    config: AgentConfig | None = None
    repeats: int | None = Field(default=None, ge=1, le=100)
    task_ids: list[str] | None = None

    @model_validator(mode="after")
    def _exactly_one_agent(self) -> BenchmarkRunCreate:
        if (self.agent_id is None) == (self.config is None):
            raise ValueError("provide exactly one of agent_id or config")
        return self


class ExperimentCreate(_Request):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    suite_id: str
    base_agent_id: str | None = None
    base_config: AgentConfig | None = None
    variants: list[Variant] = Field(min_length=1)
    repeats: int | None = Field(default=None, ge=1, le=100)
    task_ids: list[str] | None = None

    @model_validator(mode="after")
    def _exactly_one_base(self) -> ExperimentCreate:
        if (self.base_agent_id is None) == (self.base_config is None):
            raise ValueError("provide exactly one of base_agent_id or base_config")
        return self


class SuiteInfo(BaseModel):
    id: str
    name: str
    description: str
    version: str
    repeats: int
    tasks: list[dict[str, Any]]
    path: str


class Health(BaseModel):
    status: str
    version: str
    database: str


class ImprovementCreate(_Request):
    benchmark_run_id: str
    changes: list[ProposedChange] | None = Field(
        default=None,
        description="Developer-written changes; omit to use the rule-based proposer.",
        max_length=50,
    )
    notes: str = Field(default="", max_length=10_000)


class ImprovementApply(_Request):
    change_ids: list[str] | None = Field(
        default=None, description="Subset of proposal change ids to apply (default: all)."
    )


class ImprovementReject(_Request):
    reason: str = Field(default="", max_length=10_000)
