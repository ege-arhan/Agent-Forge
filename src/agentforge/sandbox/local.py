"""Host-process sandbox (development only - provides NO isolation)."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time

from agentforge.core.errors import SandboxError
from agentforge.sandbox.base import DEFAULT_OUTPUT_LIMIT, ExecResult, Sandbox, read_capped

# Environment variables passed through to child processes. Everything else -
# in particular API keys and tokens held by the AgentForge process - is dropped.
_PASSTHROUGH_ENV = ("PATH", "LANG", "LC_ALL", "TZ", "TERM")


async def run_process(
    argv: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    timeout: float,
    stdin: str | None,
    output_limit: int,
) -> ExecResult:
    """Run a host process with a timeout, killing its whole process group."""
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise SandboxError(f"executable not found: {argv[0]}") from exc
    except OSError as exc:
        raise SandboxError(f"failed to start process: {exc}") from exc

    async def _communicate() -> tuple[tuple[bytes, bool], tuple[bytes, bool]]:
        if stdin is not None and proc.stdin is not None:
            proc.stdin.write(stdin.encode())
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                await proc.stdin.drain()
            proc.stdin.close()
        out, err = await asyncio.gather(
            read_capped(proc.stdout, output_limit), read_capped(proc.stderr, output_limit)
        )
        await proc.wait()
        return out, err

    timed_out = False
    try:
        (stdout, out_trunc), (stderr, err_trunc) = await asyncio.wait_for(
            _communicate(), timeout=timeout
        )
    except TimeoutError:
        timed_out = True
        _kill_group(proc)
        await proc.wait()
        stdout, stderr, out_trunc, err_trunc = b"", b"", False, False
    except asyncio.CancelledError:
        _kill_group(proc)
        raise

    return ExecResult(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace")
        + (f"\n[command timed out after {timeout:g}s]" if timed_out else ""),
        duration_ms=int((time.monotonic() - started) * 1000),
        timed_out=timed_out,
        truncated=out_trunc or err_trunc,
    )


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)


class LocalSandbox(Sandbox):
    """Runs commands as host processes confined only by working directory.

    This is a convenience for trusted local development. Commands can read
    and write anything the AgentForge process can. Use ``DockerSandbox`` for
    untrusted agents.
    """

    isolation = "none"

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
        workdir = self.workspace.resolve(cwd)
        child_env = {k: os.environ[k] for k in _PASSTHROUGH_ENV if k in os.environ}
        child_env["HOME"] = str(self.workspace.root)
        child_env.update(env or {})
        return await run_process(
            argv,
            cwd=str(workdir),
            env=child_env,
            timeout=timeout,
            stdin=stdin,
            output_limit=output_limit,
        )
