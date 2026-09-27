"""Declarative agent configuration.

An :class:`AgentConfig` fully describes how an agent is assembled: which model
it talks to, which tools it may use, its memory settings, run limits, retry
policy, planning strategy and sandbox. Configs are plain data (YAML/JSON
friendly) and a snapshot is stored with every run so runs are reproducible.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelConfig(_Strict):
    """Which LLM provider/model to use and how to call it."""

    provider: str = Field(
        description="Provider id: anthropic, openai, openrouter, gemini, local, scripted, ..."
    )
    model: str = Field(default="", description="Provider-specific model identifier.")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=200_000)
    base_url: str | None = Field(
        default=None, description="Override the provider endpoint (OpenAI-compatible servers)."
    )
    api_key_env: str | None = Field(
        default=None,
        description="Name of the environment variable holding the API key. The key itself is "
        "never stored in configs or runs.",
    )
    options: dict[str, Any] = Field(
        default_factory=dict, description="Provider-specific extra options."
    )


class RunLimits(_Strict):
    max_steps: int = Field(default=20, ge=1, le=500)
    timeout_seconds: float = Field(default=600.0, gt=0, le=86_400)
    max_tool_calls: int = Field(default=100, ge=0, le=5_000)
    max_consecutive_tool_errors: int = Field(default=5, ge=1, le=100)
    max_total_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Stop the run once reported input+output tokens reach this budget "
        "(off by default; providers that report no usage are not limited).",
    )
    max_output_chars: int = Field(
        default=20_000, ge=256, description="Tool output is truncated beyond this size."
    )


class RetryPolicy(_Strict):
    """Retry behaviour for transient LLM failures and failed evaluations."""

    llm_max_attempts: int = Field(default=3, ge=1, le=10)
    backoff_initial_seconds: float = Field(default=1.0, ge=0.0, le=60.0)
    backoff_max_seconds: float = Field(default=30.0, ge=0.0, le=600.0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0, le=10.0)
    evaluation_retries: int = Field(
        default=0,
        ge=0,
        le=10,
        description="How many times the agent is asked to continue after a failed evaluation.",
    )


class PlannerStrategy(StrEnum):
    REACT = "react"
    PLAN_EXECUTE = "plan_execute"


class PlannerConfig(_Strict):
    strategy: PlannerStrategy = PlannerStrategy.REACT
    max_plan_steps: int = Field(default=10, ge=1, le=50)


class MemoryConfig(_Strict):
    enabled: bool = True
    persist: bool = Field(
        default=False, description="Store a summary of each run in persistent agent memory."
    )
    recall_limit: int = Field(default=5, ge=0, le=50)
    keep_recent_messages: int = Field(
        default=40,
        ge=4,
        le=1_000,
        description="Short-term memory window: older tool outputs are compacted beyond this.",
    )


class SandboxKind(StrEnum):
    LOCAL = "local"
    DOCKER = "docker"


_DOCKER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_PROXY_RE = re.compile(r"^https?://[A-Za-z0-9_.:\[\]-]+/?$")


class SandboxConfig(_Strict):
    kind: SandboxKind = SandboxKind.LOCAL
    image: str = "python:3.12-slim"
    network: str = Field(
        default="none",
        description="'none' (default), 'bridge', or the name of an operator-created Docker "
        "network (e.g. an internal network behind an egress proxy).",
    )
    runtime: str | None = Field(
        default=None, description="Docker runtime, e.g. 'runsc' for gVisor isolation."
    )
    proxy: str | None = Field(
        default=None,
        description="HTTP(S) proxy URL injected into the sandbox (e.g. the egress proxy).",
    )
    memory: str = "512m"
    cpus: float = Field(default=1.0, gt=0, le=64)
    pids_limit: int = Field(default=256, ge=16, le=65_536)
    command_timeout_seconds: float = Field(default=120.0, gt=0, le=3_600)

    @field_validator("network", "runtime")
    @classmethod
    def _docker_name(cls, value: str | None) -> str | None:
        if value is not None and not _DOCKER_NAME_RE.match(value):
            raise ValueError("must be a valid Docker network/runtime name")
        return value

    @field_validator("proxy")
    @classmethod
    def _proxy_url(cls, value: str | None) -> str | None:
        if value is not None and not _PROXY_RE.match(value):
            raise ValueError("proxy must look like http://host:port")
        return value


_KNOWN_PERMISSIONS = frozenset(
    {
        "fs:read",
        "fs:write",
        "process:exec",
        "network",
        "git:read",
        "git:write",
        "github:read",
        "github:write",
        "memory",
    }
)  # mirrors agentforge.tools.base.Permission values; duplicated here so core does not
# depend on tools (tools already depends on core). A test asserts the two stay in sync.


class ApprovalPolicy(_Strict):
    """Pause a run and wait for a human decision before tools that need it."""

    require_for: frozenset[str] = Field(
        default_factory=frozenset,
        description="Tool permissions that require approval before use, e.g. 'fs:write', "
        "'network', 'process:exec', 'git:write', 'github:write'.",
    )
    timeout_seconds: float = Field(
        default=3600.0,
        gt=0,
        le=86_400,
        description="How long to wait for a decision before denying the call and continuing.",
    )

    @field_validator("require_for")
    @classmethod
    def _validate_permissions(cls, value: frozenset[str]) -> frozenset[str]:
        unknown = value - _KNOWN_PERMISSIONS
        if unknown:
            raise ValueError(
                f"unknown permission(s) for approval.require_for: {sorted(unknown)}; "
                f"valid values are {sorted(_KNOWN_PERMISSIONS)}"
            )
        return value


class AgentConfig(_Strict):
    """Complete, serialisable description of an agent."""

    name: str
    description: str = ""
    model: ModelConfig
    system_prompt: str = Field(
        default="You are a careful, capable software agent. Use the available tools to "
        "accomplish the user's goal, verify your work, and finish with a concise summary."
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Tool or toolset names (filesystem, terminal, git, http, github, memory).",
    )
    tool_settings: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Per-tool settings keyed by tool name."
    )
    limits: RunLimits = Field(default_factory=RunLimits)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    planner: PlannerConfig = Field(default_factory=PlannerConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    approval: ApprovalPolicy = Field(default_factory=ApprovalPolicy)
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError(
                "name must be 1-64 chars of letters, digits, '_', '-', '.', "
                "starting with a letter or digit"
            )
        return value
