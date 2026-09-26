from __future__ import annotations

from pathlib import Path

import pytest

from agentforge.core.config import SandboxConfig, SandboxKind
from agentforge.core.errors import ConfigurationError, SandboxError
from agentforge.llm.types import Message, Role, ToolResultPart, ToolUsePart
from agentforge.memory.base import InMemoryMemoryStore, MemoryRecord, MemoryScope, lexical_rank
from agentforge.memory.context import compact_history
from agentforge.sandbox import create_sandbox
from agentforge.sandbox.docker import DockerSandbox, build_exec_args, build_run_args
from agentforge.sandbox.local import LocalSandbox
from agentforge.sandbox.workspace import Workspace


def rec(content: str, ns: str = "a") -> MemoryRecord:
    return MemoryRecord(scope=MemoryScope.AGENT, namespace=ns, content=content)


def test_lexical_rank_orders_by_relevance() -> None:
    records = [
        rec("python tests use pytest"),
        rec("the database is postgres"),
        rec("pytest fixtures"),
    ]
    ranked = lexical_rank("how do I run pytest tests", records, limit=5)
    assert [r.record.content for r in ranked][:1] == ["python tests use pytest"]
    assert all(r.record.content != "the database is postgres" for r in ranked)
    assert lexical_rank("", records, 5) == []


async def test_in_memory_store_scoping() -> None:
    store = InMemoryMemoryStore()
    await store.add(rec("alpha fact", ns="a"))
    await store.add(rec("alpha fact", ns="b"))
    assert len(await store.list_records(MemoryScope.AGENT, "a")) == 1
    hits = await store.search(MemoryScope.AGENT, "b", "alpha")
    assert len(hits) == 1
    assert await store.delete(hits[0].record.id)
    assert not await store.delete("missing")


def _pair(i: int, size: int) -> list[Message]:
    return [
        Message(role=Role.ASSISTANT, content=[ToolUsePart(id=f"t{i}", name="x")]),
        Message(role=Role.USER, content=[ToolResultPart(tool_use_id=f"t{i}", content="y" * size)]),
    ]


def test_compact_history_elides_old_tool_output_only() -> None:
    messages = [Message.user("goal")]
    for i in range(6):
        messages += _pair(i, 5_000)
    compacted = compact_history(messages, keep_recent=4)
    assert compacted[0] == messages[0]
    old = compacted[2].content[0]
    assert isinstance(old, ToolResultPart) and "elided" in old.content and old.tool_use_id == "t0"
    recent = compacted[-1].content[0]
    assert isinstance(recent, ToolResultPart) and len(recent.content) == 5_000
    assert len(compacted) == len(messages)
    assert compact_history(messages[:3], keep_recent=10) == messages[:3]


def test_docker_run_args_are_hardened(workspace: Workspace) -> None:
    args = build_run_args(SandboxConfig(kind=SandboxKind.DOCKER), workspace, "c1", "1000:1000")
    joined = " ".join(args)
    for flag in [
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--pids-limit 256",
        "--memory 512m",
        "--user 1000:1000",
    ]:
        assert flag in joined, flag
    assert f"{workspace.root}:/workspace:rw" in args
    assert args[-3:] == ["python:3.12-slim", "sleep", "infinity"]


def test_docker_exec_args() -> None:
    args = build_exec_args(
        "c1", ["sh", "-c", "ls"], workdir="/workspace/src", timeout=30.5, env={"A": "1"}
    )
    assert args[:5] == ["docker", "exec", "--interactive", "--workdir", "/workspace/src"]
    assert args[-3:] == ["sh", "-c", "ls"]
    assert "--env" in args and "A=1" in args
    assert args[args.index("c1") + 1 : args.index("c1") + 5] == ["timeout", "-s", "KILL", "30"]
    with pytest.raises(SandboxError):
        build_exec_args("c1", ["ls"], workdir="/workspace", timeout=1, env={"BAD NAME": "x"})


def test_create_sandbox_policy(workspace: Workspace) -> None:
    assert isinstance(create_sandbox(SandboxConfig(), workspace), LocalSandbox)
    assert isinstance(
        create_sandbox(SandboxConfig(kind=SandboxKind.DOCKER), workspace), DockerSandbox
    )
    with pytest.raises(ConfigurationError):
        create_sandbox(SandboxConfig(), workspace, allow_local=False)


async def test_local_sandbox_confines_cwd(workspace: Workspace) -> None:
    sandbox = LocalSandbox(workspace)
    (workspace.root / "sub").mkdir()
    result = await sandbox.exec(["pwd"], cwd="sub")
    assert Path(result.stdout.strip()) == workspace.root / "sub"
    with pytest.raises(Exception, match="outside the workspace"):
        await sandbox.exec(["pwd"], cwd="..")
    with pytest.raises(SandboxError):
        await sandbox.exec(["definitely-not-a-binary-xyz"])


async def test_local_sandbox_output_cap(workspace: Workspace) -> None:
    result = await LocalSandbox(workspace).exec(
        ["sh", "-c", "yes | head -c 200000"], output_limit=1000
    )
    assert result.truncated and len(result.stdout) == 1000


async def test_sandbox_does_not_serve_stale_python_bytecode(workspace: Workspace) -> None:
    """Regression: editing a module within the same second (same size) and re-running it
    used to execute the stale cached bytecode."""
    sandbox = LocalSandbox(workspace)
    workspace.write_files(
        {"mod.py": "def f():\n    return 1\n", "main.py": "import mod\nprint(mod.f())\n"}
    )
    first = await sandbox.exec(["python3", "main.py"])
    (workspace.root / "mod.py").write_text("def f():\n    return 2\n")
    second = await sandbox.exec(["python3", "main.py"])
    assert (first.stdout.strip(), second.stdout.strip()) == ("1", "2")
    assert "PYTHONDONTWRITEBYTECODE=1" in " ".join(
        build_run_args(SandboxConfig(kind=SandboxKind.DOCKER), workspace, "c", None)
    )
