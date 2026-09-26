"""Command execution sandboxes and workspaces."""

from __future__ import annotations

from agentforge.core.config import SandboxConfig, SandboxKind
from agentforge.core.errors import ConfigurationError
from agentforge.sandbox.base import ExecResult, Sandbox
from agentforge.sandbox.docker import DockerSandbox
from agentforge.sandbox.local import LocalSandbox
from agentforge.sandbox.workspace import Workspace

__all__ = [
    "DockerSandbox",
    "ExecResult",
    "LocalSandbox",
    "Sandbox",
    "Workspace",
    "create_sandbox",
]


def create_sandbox(
    config: SandboxConfig, workspace: Workspace, *, allow_local: bool = True
) -> Sandbox:
    if config.kind == SandboxKind.DOCKER:
        return DockerSandbox(workspace, config)
    if not allow_local:
        raise ConfigurationError(
            "the local (unisolated) sandbox is disabled on this server; use sandbox.kind=docker"
        )
    return LocalSandbox(workspace)
