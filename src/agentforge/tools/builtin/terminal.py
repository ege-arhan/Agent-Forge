"""Shell command execution inside the run's sandbox."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from agentforge.tools.base import Permission, Tool, ToolContext, ToolInput, ToolOutput


class RunCommandInput(ToolInput):
    command: str = Field(min_length=1, max_length=10_000, description="Shell command (sh -c).")
    cwd: str = Field(default=".", description="Working directory relative to the workspace.")
    timeout_seconds: float | None = Field(
        default=None, gt=0, le=3_600, description="Override the default command timeout."
    )
    stdin: str | None = Field(default=None, max_length=1_000_000)


def format_exec(exit_code: int, stdout: str, stderr: str, timed_out: bool) -> str:
    parts = [f"exit_code: {exit_code}" + (" (timed out)" if timed_out else "")]
    if stdout:
        parts.append(f"stdout:\n{stdout.rstrip()}")
    if stderr:
        parts.append(f"stderr:\n{stderr.rstrip()}")
    return "\n".join(parts)


class RunCommand(Tool[RunCommandInput]):
    name = "run_command"
    description = (
        "Run a shell command in the sandboxed workspace and return exit code, stdout and "
        "stderr. Non-zero exit codes are reported, not raised. Avoid interactive commands."
    )
    input_model = RunCommandInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.PROCESS_EXEC})
    # The executor-level timeout is a backstop; the sandbox enforces the
    # per-command timeout and kills the process tree.
    timeout_seconds = 3_700.0

    async def run(self, args: RunCommandInput, ctx: ToolContext) -> ToolOutput:
        settings: dict[str, Any] = ctx.settings.get(self.name, {})
        default_timeout = float(settings.get("command_timeout_seconds", 120.0))
        timeout = args.timeout_seconds or default_timeout
        max_timeout = float(settings.get("max_command_timeout_seconds", 600.0))
        timeout = min(timeout, max_timeout)
        result = await ctx.sandbox.exec(
            ["sh", "-c", args.command], cwd=args.cwd, timeout=timeout, stdin=args.stdin
        )
        return ToolOutput(
            content=format_exec(result.exit_code, result.stdout, result.stderr, result.timed_out),
            is_error=result.timed_out,
            data={"exit_code": result.exit_code, "timed_out": result.timed_out},
        )


TERMINAL_TOOLS: list[type[Tool[Any]]] = [RunCommand]
