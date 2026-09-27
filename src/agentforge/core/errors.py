"""Exception hierarchy shared across AgentForge components."""

from __future__ import annotations


class AgentForgeError(Exception):
    """Base class for all AgentForge errors."""

    code: str = "agentforge_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class ConfigurationError(AgentForgeError):
    code = "configuration_error"


class NotFoundError(AgentForgeError):
    code = "not_found"


class LLMError(AgentForgeError):
    """An error raised by an LLM provider.

    ``retryable`` tells the runtime whether the retry policy may re-issue the
    request (rate limits, transient server and connection errors).
    """

    code = "llm_error"

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message, code=code)
        self.retryable = retryable
        self.status_code = status_code


class ToolError(AgentForgeError):
    """A tool failed in a way that should be reported back to the model."""

    code = "tool_error"


class PermissionDeniedError(ToolError):
    code = "permission_denied"


class SandboxError(AgentForgeError):
    code = "sandbox_error"


class WorkspaceError(ToolError):
    """Invalid path or operation outside the workspace boundary."""

    code = "workspace_error"


class RunCancelledError(AgentForgeError):
    code = "cancelled"


class BenchmarkError(AgentForgeError):
    code = "benchmark_error"


class CapacityError(AgentForgeError):
    """The server is at capacity (too many queued background tasks)."""

    code = "capacity"


class ImprovementError(AgentForgeError):
    """An improvement-loop operation is not valid in the cycle's current state."""

    code = "improvement_error"
