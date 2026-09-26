"""Tool interface.

A tool declares its name, description, a Pydantic input model (from which the
JSON schema shown to the model is generated), the permissions it needs and a
default timeout. The :class:`~agentforge.tools.executor.ToolExecutor` wraps
every invocation with validation, permission checks, timeouts, error capture,
output truncation and secret redaction, so tool implementations can stay small.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ConfigDict

from agentforge.llm.types import ToolSpec

if TYPE_CHECKING:
    from agentforge.memory.base import MemoryStore
    from agentforge.observability.redaction import Redactor
    from agentforge.sandbox.base import Sandbox
    from agentforge.sandbox.workspace import Workspace


class Permission(StrEnum):
    FS_READ = "fs:read"
    FS_WRITE = "fs:write"
    PROCESS_EXEC = "process:exec"
    NETWORK = "network"
    GIT_READ = "git:read"
    GIT_WRITE = "git:write"
    GITHUB_READ = "github:read"
    GITHUB_WRITE = "github:write"
    MEMORY = "memory"


class ToolInput(BaseModel):
    """Base class for tool input models (rejects unknown fields)."""

    model_config = ConfigDict(extra="forbid")


@dataclass
class ToolContext:
    """Everything a tool may touch during a run."""

    run_id: str
    workspace: Workspace
    sandbox: Sandbox
    redactor: Redactor
    settings: dict[str, Any] = field(default_factory=dict)
    memory: MemoryStore | None = None
    agent_id: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class ToolOutput:
    content: str
    is_error: bool = False
    data: dict[str, Any] | None = None

    @classmethod
    def error(cls, message: str) -> ToolOutput:
        return cls(content=message, is_error=True)


class Tool[InputT: ToolInput](ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[ToolInput]]
    permissions: ClassVar[frozenset[Permission]] = frozenset()
    timeout_seconds: ClassVar[float] = 30.0

    @abstractmethod
    async def run(self, args: InputT, ctx: ToolContext) -> ToolOutput:
        """Execute the tool. Raise ``ToolError`` for expected failures."""

    @classmethod
    def spec(cls) -> ToolSpec:
        schema = cls.input_model.model_json_schema()
        schema.pop("title", None)
        return ToolSpec(name=cls.name, description=cls.description, input_schema=schema)
