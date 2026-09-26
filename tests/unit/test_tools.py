from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import Any, ClassVar

import httpx
import pytest

from agentforge.core.errors import ConfigurationError, WorkspaceError
from agentforge.core.models import ToolCallStatus
from agentforge.llm.types import ToolUsePart
from agentforge.observability.redaction import REDACTED
from agentforge.sandbox.workspace import Workspace
from agentforge.tools.base import Permission, Tool, ToolContext, ToolInput, ToolOutput
from agentforge.tools.builtin.filesystem import (
    EditFile,
    ListDirectory,
    ReadFile,
    SearchFiles,
    WriteFile,
)
from agentforge.tools.builtin.git import GitBranch, GitCommit, GitDiff, GitLog, GitStatus
from agentforge.tools.builtin.github import GitHubCreatePullRequest, GitHubGetIssue
from agentforge.tools.builtin.http import HttpRequest, host_allowed
from agentforge.tools.builtin.memory import Recall, Remember
from agentforge.tools.builtin.terminal import RunCommand
from agentforge.tools.executor import ToolExecutor, truncate
from agentforge.tools.registry import ToolRegistry, default_registry


def call(tool: str, /, **arguments: Any) -> ToolUsePart:
    return ToolUsePart(id=f"c_{tool}", name=tool, arguments=arguments)


# ------------------------------------------------------------------ workspace
def test_workspace_rejects_escapes(workspace: Workspace, tmp_path: Any) -> None:
    for bad in ["../outside.txt", "/etc/passwd", "a/../../x"]:
        with pytest.raises(WorkspaceError):
            workspace.resolve(bad)
    (tmp_path / "secret.txt").write_text("s")
    os.symlink(tmp_path / "secret.txt", workspace.root / "link")
    with pytest.raises(WorkspaceError):
        workspace.resolve("link")
    assert workspace.resolve("sub/../file.txt") == workspace.root / "file.txt"
    assert workspace.resolve(str(workspace.root / "inside")) == workspace.root / "inside"


# ------------------------------------------------------------------- registry
def test_default_registry_has_toolsets() -> None:
    registry = default_registry()
    sets = registry.toolsets()
    for name in ["filesystem", "terminal", "git", "http", "github", "memory"]:
        assert sets[name], name
    resolved = registry.resolve(["filesystem", "read_file", "run_command"])
    assert [t.name for t in resolved].count("read_file") == 1
    info = {i.name: i for i in registry.describe()}
    assert info["run_command"].permissions == ["process:exec"]
    assert info["read_file"].input_schema["properties"]["path"]["type"] == "string"


def test_registry_rejects_duplicates_and_unknown() -> None:
    registry = ToolRegistry()
    registry.register(ReadFile, toolset="fs")

    class Other(ReadFile):
        pass

    with pytest.raises(ConfigurationError):
        registry.register(Other)
    with pytest.raises(ConfigurationError):
        registry.resolve(["missing"])


# ------------------------------------------------------------------- executor
class SlowInput(ToolInput):
    seconds: float = 5


class SlowTool(Tool[SlowInput]):
    name = "slow"
    description = "sleeps"
    input_model = SlowInput
    timeout_seconds = 0.05

    async def run(self, args: SlowInput, ctx: ToolContext) -> ToolOutput:
        await asyncio.sleep(args.seconds)
        return ToolOutput(content="done")


class CrashTool(Tool[ToolInput]):
    name = "crash"
    description = "raises"
    input_model = ToolInput

    async def run(self, args: ToolInput, ctx: ToolContext) -> ToolOutput:
        raise RuntimeError("super-secret-value leaked in exception")


class EchoInput(ToolInput):
    text: str


class EchoTool(Tool[EchoInput]):
    name = "echo"
    description = "echo"
    input_model = EchoInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.NETWORK})

    async def run(self, args: EchoInput, ctx: ToolContext) -> ToolOutput:
        return ToolOutput(content=args.text)


async def test_executor_unknown_tool(tool_ctx: ToolContext) -> None:
    record, result = await ToolExecutor([], tool_ctx).execute(call("nope"))
    assert record.status == ToolCallStatus.INVALID_INPUT
    assert result.is_error


async def test_executor_validates_input(tool_ctx: ToolContext) -> None:
    executor = ToolExecutor([EchoTool()], tool_ctx)
    record, result = await executor.execute(call("echo", wrong=1))
    assert record.status == ToolCallStatus.INVALID_INPUT
    assert "text" in result.content
    record, _ = await executor.execute(
        ToolUsePart(id="x", name="echo", arguments={"__invalid_json__": "{"})
    )
    assert record.status == ToolCallStatus.INVALID_INPUT


async def test_executor_enforces_denied_permissions(tool_ctx: ToolContext) -> None:
    executor = ToolExecutor([EchoTool()], tool_ctx, denied_permissions={Permission.NETWORK})
    record, _ = await executor.execute(call("echo", text="x"))
    assert record.status == ToolCallStatus.DENIED


async def test_executor_timeout(tool_ctx: ToolContext) -> None:
    record, result = await ToolExecutor([SlowTool()], tool_ctx).execute(call("slow"))
    assert record.status == ToolCallStatus.TIMEOUT
    assert result.is_error


async def test_executor_timeout_override_from_settings(tool_ctx: ToolContext) -> None:
    tool_ctx.settings = {"slow": {"timeout_seconds": 1}}
    record, _ = await ToolExecutor([SlowTool()], tool_ctx).execute(call("slow", seconds=0.1))
    assert record.status == ToolCallStatus.SUCCESS


async def test_executor_contains_crashes_and_redacts(tool_ctx: ToolContext) -> None:
    record, result = await ToolExecutor([CrashTool()], tool_ctx).execute(call("crash"))
    assert record.status == ToolCallStatus.ERROR
    assert "super-secret-value" not in result.content


async def test_executor_redacts_arguments_and_output(tool_ctx: ToolContext) -> None:
    executor = ToolExecutor([EchoTool()], tool_ctx)
    record, result = await executor.execute(call("echo", text="token super-secret-value"))
    assert REDACTED in record.arguments["text"]
    assert REDACTED in result.content and REDACTED in record.output


async def test_executor_truncates(tool_ctx: ToolContext) -> None:
    executor = ToolExecutor([EchoTool()], tool_ctx, max_output_chars=300)
    record, result = await executor.execute(call("echo", text="x" * 5000))
    assert record.truncated
    assert len(result.content) < 400


def test_truncate_keeps_head_and_tail() -> None:
    text, truncated = truncate("A" * 100 + "B" * 100, 50)
    assert truncated and text.startswith("A") and text.endswith("B")


# ----------------------------------------------------------------- filesystem
async def test_filesystem_tools(tool_ctx: ToolContext) -> None:
    ex = ToolExecutor(
        [ReadFile(), WriteFile(), EditFile(), ListDirectory(), SearchFiles()], tool_ctx
    )
    rec, _ = await ex.execute(call("write_file", path="src/app.py", content="x = 1\ny = 2\n"))
    assert rec.status == ToolCallStatus.SUCCESS
    rec, res = await ex.execute(call("read_file", path="src/app.py"))
    assert "1\tx = 1" in res.content
    rec, res = await ex.execute(call("read_file", path="src/app.py", start_line=2, max_lines=1))
    assert "y = 2" in res.content and "x = 1" not in res.content
    rec, _ = await ex.execute(
        call("edit_file", path="src/app.py", old_text="y = 2", new_text="y = 3")
    )
    assert (tool_ctx.workspace.root / "src/app.py").read_text() == "x = 1\ny = 3\n"
    rec, res = await ex.execute(
        call("edit_file", path="src/app.py", old_text="missing", new_text="")
    )
    assert rec.status == ToolCallStatus.ERROR
    rec, res = await ex.execute(call("list_directory", recursive=True))
    assert res.content.splitlines() == ["src/", "src/app.py"]
    rec, res = await ex.execute(call("search_files", pattern=r"y = \d", glob="*.py"))
    assert res.content == "src/app.py:2: y = 3"
    rec, res = await ex.execute(call("read_file", path="../escape"))
    assert rec.status == ToolCallStatus.ERROR
    assert "outside the workspace" in res.content


async def test_edit_file_ambiguous(tool_ctx: ToolContext) -> None:
    (tool_ctx.workspace.root / "f.txt").write_text("a a a")
    ex = ToolExecutor([EditFile()], tool_ctx)
    rec, _ = await ex.execute(call("edit_file", path="f.txt", old_text="a", new_text="b"))
    assert rec.status == ToolCallStatus.ERROR
    rec, _ = await ex.execute(
        call("edit_file", path="f.txt", old_text="a", new_text="b", replace_all=True)
    )
    assert (tool_ctx.workspace.root / "f.txt").read_text() == "b b b"


# ------------------------------------------------------------------- terminal
async def test_run_command_captures_output_and_exit_code(tool_ctx: ToolContext) -> None:
    ex = ToolExecutor([RunCommand()], tool_ctx)
    rec, res = await ex.execute(call("run_command", command="echo hi; echo err >&2; exit 3"))
    assert rec.status == ToolCallStatus.SUCCESS  # non-zero exit is a result, not a tool failure
    assert "exit_code: 3" in res.content and "hi" in res.content and "err" in res.content


async def test_run_command_does_not_leak_environment(
    tool_ctx: ToolContext, monkeypatch: Any
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-be-visible")
    ex = ToolExecutor([RunCommand()], tool_ctx)
    _, res = await ex.execute(call("run_command", command="env"))
    assert "should-not-be-visible" not in res.content
    assert f"HOME={tool_ctx.workspace.root}" in res.content


async def test_run_command_timeout_kills_process(tool_ctx: ToolContext) -> None:
    ex = ToolExecutor([RunCommand()], tool_ctx)
    rec, res = await ex.execute(call("run_command", command="sleep 10", timeout_seconds=0.3))
    assert rec.status == ToolCallStatus.ERROR
    assert "timed out" in res.content
    assert rec.duration_ms < 5000


# ------------------------------------------------------------------------ git
@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
async def test_git_tools_workflow(tool_ctx: ToolContext) -> None:
    ex = ToolExecutor(
        [GitStatus(), GitDiff(), GitLog(), GitCommit(), GitBranch(), WriteFile()], tool_ctx
    )
    await tool_ctx.sandbox.exec(["git", "init", "-q", "-b", "main"])
    await ex.execute(call("write_file", path="a.txt", content="one\n"))
    rec, res = await ex.execute(call("git_status"))
    assert "a.txt" in res.content
    rec, res = await ex.execute(call("git_commit", message="first commit"))
    assert rec.status == ToolCallStatus.SUCCESS, res.content
    rec, res = await ex.execute(call("git_branch", name="feature/x"))
    assert rec.status == ToolCallStatus.SUCCESS, res.content
    await ex.execute(call("write_file", path="a.txt", content="two\n"))
    rec, res = await ex.execute(call("git_diff"))
    assert "+two" in res.content
    rec, res = await ex.execute(call("git_log"))
    assert "first commit" in res.content
    rec, _ = await ex.execute(call("git_branch", name="--evil"))
    assert rec.status == ToolCallStatus.INVALID_INPUT
    rec, _ = await ex.execute(call("git_diff", path="--output=/tmp/x"))
    assert rec.status == ToolCallStatus.INVALID_INPUT


# ----------------------------------------------------------------------- http
def test_host_allowlist_matching() -> None:
    assert host_allowed("api.example.com", ["*.example.com"])
    assert host_allowed("Example.com.", ["example.com"])
    assert not host_allowed("evil.com", ["example.com"])


async def _public(host: str, port: int) -> list[str]:
    return ["93.184.216.34"]


async def _private(host: str, port: int) -> list[str]:
    return ["10.0.0.5"]


async def test_http_request_success(tool_ctx: ToolContext, monkeypatch: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, text="hello world", headers={"content-type": "text/plain"})

    monkeypatch.setattr(HttpRequest, "transport", httpx.MockTransport(handler))
    monkeypatch.setattr(HttpRequest, "resolver", staticmethod(_public))
    rec, res = await ToolExecutor([HttpRequest()], tool_ctx).execute(
        call("http_request", url="https://example.com/redirect")
    )
    assert rec.status == ToolCallStatus.SUCCESS, res.content
    assert res.content.startswith("HTTP 200") and "hello world" in res.content


async def test_http_blocks_private_addresses(tool_ctx: ToolContext, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        HttpRequest, "transport", httpx.MockTransport(lambda r: httpx.Response(200))
    )
    monkeypatch.setattr(HttpRequest, "resolver", staticmethod(_private))
    ex = ToolExecutor([HttpRequest()], tool_ctx)
    rec, _ = await ex.execute(call("http_request", url="http://internal.example/"))
    assert rec.status == ToolCallStatus.DENIED
    rec, _ = await ex.execute(call("http_request", url="file:///etc/passwd"))
    assert rec.status == ToolCallStatus.ERROR


async def test_http_blocks_redirect_to_private(tool_ctx: ToolContext, monkeypatch: Any) -> None:
    async def resolver(host: str, port: int) -> list[str]:
        return ["127.0.0.1"] if host == "localhost" else ["93.184.216.34"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://localhost/admin"})

    monkeypatch.setattr(HttpRequest, "transport", httpx.MockTransport(handler))
    monkeypatch.setattr(HttpRequest, "resolver", staticmethod(resolver))
    rec, _ = await ToolExecutor([HttpRequest()], tool_ctx).execute(
        call("http_request", url="https://example.com/")
    )
    assert rec.status == ToolCallStatus.DENIED


async def test_http_allowlist_and_truncation(tool_ctx: ToolContext, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        HttpRequest,
        "transport",
        httpx.MockTransport(lambda r: httpx.Response(200, text="z" * 5000)),
    )
    monkeypatch.setattr(HttpRequest, "resolver", staticmethod(_public))
    tool_ctx.settings = {
        "http_request": {"allowed_hosts": ["example.com"], "max_response_bytes": 100}
    }
    ex = ToolExecutor([HttpRequest()], tool_ctx)
    rec, _ = await ex.execute(call("http_request", url="https://other.com/"))
    assert rec.status == ToolCallStatus.DENIED
    rec, res = await ex.execute(call("http_request", url="https://example.com/"))
    assert rec.status == ToolCallStatus.SUCCESS
    assert "truncated at 100 bytes" in res.content


# --------------------------------------------------------------------- github
async def test_github_tools_enforce_allowlist_and_open_draft_prs(
    tool_ctx: ToolContext, monkeypatch: Any
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/pulls"):
            body = json.loads(request.content)
            return httpx.Response(
                201,
                json={
                    "number": 7,
                    "title": body["title"],
                    "html_url": "https://gh/pr/7",
                    "state": "open",
                    "draft": body["draft"],
                    "head": {"ref": body["head"]},
                    "base": {"ref": body["base"]},
                },
            )
        if request.url.path.endswith("/comments"):
            return httpx.Response(200, json=[{"user": {"login": "bob"}, "body": "please fix"}])
        return httpx.Response(
            200,
            json={
                "number": 3,
                "title": "Bug",
                "body": "It breaks",
                "state": "open",
                "html_url": "https://gh/issues/3",
                "labels": [{"name": "bug"}],
                "user": {"login": "alice"},
            },
        )

    monkeypatch.setattr(GitHubGetIssue, "transport", httpx.MockTransport(handler))
    monkeypatch.setattr(GitHubCreatePullRequest, "transport", httpx.MockTransport(handler))
    tool_ctx.settings = {"github": {"repositories": ["acme/app"]}}
    tool_ctx.env = {"GITHUB_TOKEN": "ghp_" + "t" * 36}
    ex = ToolExecutor([GitHubGetIssue(), GitHubCreatePullRequest()], tool_ctx)

    rec, _ = await ex.execute(call("github_get_issue", repo="other/repo", number=1))
    assert rec.status == ToolCallStatus.DENIED
    assert not requests

    rec, res = await ex.execute(call("github_get_issue", repo="acme/app", number=3))
    assert rec.status == ToolCallStatus.SUCCESS, res.content
    assert "It breaks" in res.content and "bob: please fix" in res.content
    assert requests[0].headers["authorization"].startswith("Bearer ghp_")

    rec, res = await ex.execute(
        call("github_create_pull_request", repo="acme/app", title="Fix", head="fix-3", base="main")
    )
    assert rec.status == ToolCallStatus.SUCCESS, res.content
    assert "draft PR #7" in res.content
    assert json.loads(requests[-1].content)["draft"] is True


def test_no_merge_tool_exists() -> None:
    assert not [t for t in default_registry().describe() if "merge" in t.name]


# --------------------------------------------------------------------- memory
async def test_memory_tools_roundtrip(tool_ctx: ToolContext) -> None:
    ex = ToolExecutor([Remember(), Recall()], tool_ctx)
    await ex.execute(call("remember", content="The deploy script lives in scripts/deploy.sh"))
    await ex.execute(call("remember", content="Tests use pytest with asyncio mode"))
    rec, res = await ex.execute(call("recall", query="where is the deploy script"))
    assert rec.status == ToolCallStatus.SUCCESS
    assert res.content.splitlines()[0].endswith("scripts/deploy.sh")


async def test_memory_tools_require_store(tool_ctx: ToolContext) -> None:
    tool_ctx.memory = None
    rec, _ = await ToolExecutor([Remember()], tool_ctx).execute(call("remember", content="x"))
    assert rec.status == ToolCallStatus.ERROR
