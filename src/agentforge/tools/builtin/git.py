"""Git tools. Commands run inside the sandbox with fixed argv (no shell)."""

from __future__ import annotations

import re
from typing import Any, ClassVar

from pydantic import Field, field_validator

from agentforge.core.errors import ToolError
from agentforge.tools.base import Permission, Tool, ToolContext, ToolInput, ToolOutput
from agentforge.tools.builtin.terminal import format_exec

# Conservative ref-name rule (subset of git check-ref-format).
_BRANCH_RE = re.compile(r"^(?!-)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}(?<![./])$")

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "AgentForge Agent",
    "GIT_AUTHOR_EMAIL": "agent@agentforge.invalid",
    "GIT_COMMITTER_NAME": "AgentForge Agent",
    "GIT_COMMITTER_EMAIL": "agent@agentforge.invalid",
    "GIT_TERMINAL_PROMPT": "0",
}


def _safe_path(value: str) -> str:
    if value.startswith("-"):
        raise ValueError("paths may not start with '-'")
    return value


async def _git(ctx: ToolContext, *args: str, timeout: float = 60.0) -> tuple[int, str]:
    env = dict(_GIT_ENV)
    env.update(ctx.settings.get("git", {}).get("env", {}))
    result = await ctx.sandbox.exec(
        ["git", "-c", "core.pager=cat", "-c", "safe.directory=*", *args], timeout=timeout, env=env
    )
    return result.exit_code, format_exec(
        result.exit_code, result.stdout, result.stderr, result.timed_out
    )


class GitStatusInput(ToolInput):
    pass


class GitStatus(Tool[GitStatusInput]):
    name = "git_status"
    description = "Show the working tree status (short format with branch info)."
    input_model = GitStatusInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.GIT_READ})

    async def run(self, args: GitStatusInput, ctx: ToolContext) -> ToolOutput:
        code, out = await _git(ctx, "status", "--short", "--branch")
        return ToolOutput(content=out, is_error=code != 0)


class GitDiffInput(ToolInput):
    staged: bool = False
    path: str | None = None

    @field_validator("path")
    @classmethod
    def _check_path(cls, value: str | None) -> str | None:
        return value if value is None else _safe_path(value)


class GitDiff(Tool[GitDiffInput]):
    name = "git_diff"
    description = "Show changes in the working tree (or staged changes)."
    input_model = GitDiffInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.GIT_READ})

    async def run(self, args: GitDiffInput, ctx: ToolContext) -> ToolOutput:
        cmd = ["diff"]
        if args.staged:
            cmd.append("--staged")
        if args.path:
            cmd += ["--", args.path]
        code, out = await _git(ctx, *cmd)
        return ToolOutput(content=out, is_error=code != 0)


class GitLogInput(ToolInput):
    max_count: int = Field(default=10, ge=1, le=200)


class GitLog(Tool[GitLogInput]):
    name = "git_log"
    description = "Show recent commits (one line each)."
    input_model = GitLogInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.GIT_READ})

    async def run(self, args: GitLogInput, ctx: ToolContext) -> ToolOutput:
        code, out = await _git(
            ctx, "log", f"--max-count={args.max_count}", "--oneline", "--decorate"
        )
        return ToolOutput(content=out, is_error=code != 0)


class GitCommitInput(ToolInput):
    message: str = Field(min_length=1, max_length=5_000)
    paths: list[str] = Field(
        default_factory=list, description="Paths to stage first; empty means stage all changes."
    )

    @field_validator("paths")
    @classmethod
    def _check_paths(cls, value: list[str]) -> list[str]:
        return [_safe_path(p) for p in value]


class GitCommit(Tool[GitCommitInput]):
    name = "git_commit"
    description = "Stage changes (all, or the given paths) and create a commit."
    input_model = GitCommitInput
    permissions: ClassVar[frozenset[Permission]] = frozenset(
        {Permission.GIT_READ, Permission.GIT_WRITE}
    )

    async def run(self, args: GitCommitInput, ctx: ToolContext) -> ToolOutput:
        add_args = ["add", "--", *args.paths] if args.paths else ["add", "--all"]
        code, out = await _git(ctx, *add_args)
        if code != 0:
            return ToolOutput(content=out, is_error=True)
        code, out = await _git(ctx, "commit", "--no-verify", "-m", args.message)
        return ToolOutput(content=out, is_error=code != 0)


class GitBranchInput(ToolInput):
    name: str = Field(description="Branch name to create or switch to.")
    create: bool = True

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if not _BRANCH_RE.match(value) or value.endswith(".lock"):
            raise ValueError("invalid branch name")
        return value


class GitBranch(Tool[GitBranchInput]):
    name = "git_branch"
    description = "Create and switch to a new branch, or switch to an existing one."
    input_model = GitBranchInput
    permissions: ClassVar[frozenset[Permission]] = frozenset(
        {Permission.GIT_READ, Permission.GIT_WRITE}
    )

    async def run(self, args: GitBranchInput, ctx: ToolContext) -> ToolOutput:
        cmd = ["switch", "-c", args.name] if args.create else ["switch", args.name]
        code, out = await _git(ctx, *cmd)
        if code != 0 and "not a git repository" in out:
            raise ToolError("the workspace is not a git repository")
        return ToolOutput(content=out, is_error=code != 0)


GIT_TOOLS: list[type[Tool[Any]]] = [GitStatus, GitDiff, GitLog, GitCommit, GitBranch]
