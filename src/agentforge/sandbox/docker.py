"""Docker-based sandbox: one locked-down container per run.

The container is started once per run with the workspace bind-mounted at
``/workspace`` and is removed when the run ends. Hardening applied by default:

* no network (``--network none``) unless explicitly configured;
* memory, CPU and PID limits;
* read-only root filesystem with a small ``/tmp`` tmpfs;
* all Linux capabilities dropped and ``no-new-privileges``;
* runs as the invoking host user (non-root) so workspace files keep sane owners;
* per-command timeouts enforced both inside the container (``timeout -s KILL``)
  and on the host.

The Docker CLI is used (instead of the Docker SDK) to avoid an extra
dependency; it must be on ``PATH`` and able to reach a daemon.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil

from agentforge.core.config import SandboxConfig
from agentforge.core.errors import SandboxError
from agentforge.core.ids import new_id
from agentforge.sandbox.base import DEFAULT_OUTPUT_LIMIT, ExecResult, Sandbox
from agentforge.sandbox.local import run_process
from agentforge.sandbox.workspace import Workspace

CONTAINER_WORKDIR = "/workspace"
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def build_run_args(
    config: SandboxConfig, workspace: Workspace, name: str, user: str | None
) -> list[str]:
    """Return the ``docker run`` argv for the long-lived sandbox container."""
    args = [
        "docker",
        "run",
        "--detach",
        "--rm",
        "--name",
        name,
        "--network",
        config.network,
        "--memory",
        config.memory,
        "--memory-swap",
        config.memory,
        "--cpus",
        f"{config.cpus:g}",
        "--pids-limit",
        str(config.pids_limit),
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",  # noqa: S108 - path inside the container
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--label",
        "agentforge.sandbox=1",
        "--volume",
        f"{workspace.root}:{CONTAINER_WORKDIR}:rw",
        "--workdir",
        CONTAINER_WORKDIR,
        "--env",
        f"HOME={CONTAINER_WORKDIR}",
    ]
    if user:
        args += ["--user", user]
    args += [config.image, "sleep", "infinity"]
    return args


def build_exec_args(
    name: str, argv: list[str], *, workdir: str, timeout: float, env: dict[str, str] | None
) -> list[str]:
    args = ["docker", "exec", "--interactive", "--workdir", workdir]
    for key, value in (env or {}).items():
        if not _ENV_NAME.match(key):
            raise SandboxError(f"invalid environment variable name: {key!r}")
        args += ["--env", f"{key}={value}"]
    seconds = max(1, int(timeout))
    args += [name, "timeout", "-s", "KILL", str(seconds), *argv]
    return args


def docker_available() -> bool:
    return shutil.which("docker") is not None


class DockerSandbox(Sandbox):
    isolation = "container"

    def __init__(self, workspace: Workspace, config: SandboxConfig | None = None) -> None:
        super().__init__(workspace)
        self.config = config or SandboxConfig()
        self.container_name = new_id("agentforge")
        self._started = False

    def _user(self) -> str | None:
        getuid = getattr(os, "getuid", None)
        getgid = getattr(os, "getgid", None)
        if getuid is None or getgid is None:  # pragma: no cover - non-POSIX
            return None
        return f"{getuid()}:{getgid()}"

    async def start(self) -> None:
        if self._started:
            return
        if not docker_available():
            raise SandboxError("docker CLI not found on PATH")
        self.workspace.create()
        args = build_run_args(self.config, self.workspace, self.container_name, self._user())
        result = await run_process(
            args,
            cwd=str(self.workspace.root),
            env=dict(os.environ),
            timeout=120,
            stdin=None,
            output_limit=8_000,
        )
        if not result.ok:
            raise SandboxError(f"failed to start sandbox container: {result.stderr.strip()}")
        self._started = True

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
        if not argv:
            raise SandboxError("empty command")
        if not self._started:
            await self.start()
        host_dir = self.workspace.resolve(cwd)
        rel = self.workspace.relative(host_dir)
        workdir = CONTAINER_WORKDIR if rel == "." else f"{CONTAINER_WORKDIR}/{rel}"
        args = build_exec_args(self.container_name, argv, workdir=workdir, timeout=timeout, env=env)
        result = await run_process(
            args,
            cwd=str(self.workspace.root),
            env=dict(os.environ),
            timeout=timeout + 10,  # host-side backstop; in-container timeout fires first
            stdin=stdin,
            output_limit=output_limit,
        )
        if result.exit_code == 137 and not result.timed_out:
            # `timeout -s KILL` exits 137 when it kills the command.
            return ExecResult(
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr + f"\n[command killed after {timeout:g}s or OOM]",
                duration_ms=result.duration_ms,
                timed_out=result.duration_ms >= int(timeout * 1000),
                truncated=result.truncated,
            )
        return result

    async def close(self) -> None:
        if not self._started:
            return
        self._started = False
        await asyncio.shield(
            run_process(
                ["docker", "rm", "--force", self.container_name],
                cwd=str(self.workspace.root),
                env=dict(os.environ),
                timeout=60,
                stdin=None,
                output_limit=4_000,
            )
        )
