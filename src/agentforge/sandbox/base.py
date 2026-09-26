"""Sandbox interface for executing untrusted commands."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass

from agentforge.sandbox.workspace import Workspace

DEFAULT_OUTPUT_LIMIT = 64_000


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class Sandbox(ABC):
    """Executes commands against a workspace.

    ``isolation`` documents the guarantee an implementation provides:
    ``"none"`` (host process, development only) or ``"container"``.
    """

    isolation: str = "none"

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def start(self) -> None:  # noqa: B027 - optional hook
        """Prepare the environment (e.g. start a container)."""

    @abstractmethod
    async def exec(
        self,
        argv: list[str],
        *,
        cwd: str = ".",
        timeout: float = 60.0,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        output_limit: int = DEFAULT_OUTPUT_LIMIT,
    ) -> ExecResult:
        """Run ``argv`` (no shell unless argv invokes one) inside the sandbox."""

    async def close(self) -> None:  # noqa: B027 - optional hook
        """Tear down resources."""

    async def __aenter__(self) -> Sandbox:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()


async def read_capped(stream: asyncio.StreamReader | None, limit: int) -> tuple[bytes, bool]:
    """Read a stream to EOF keeping at most ``limit`` bytes."""
    if stream is None:
        return b"", False
    chunks: list[bytes] = []
    size = 0
    truncated = False
    while True:
        chunk = await stream.read(65_536)
        if not chunk:
            break
        if size < limit:
            keep = chunk[: limit - size]
            chunks.append(keep)
            size += len(keep)
            if len(keep) < len(chunk):
                truncated = True
        else:
            truncated = True
    return b"".join(chunks), truncated
