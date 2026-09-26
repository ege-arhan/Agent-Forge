"""Docker sandbox tests against a real daemon (skipped when Docker is unavailable)."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from agentforge.core.config import SandboxConfig, SandboxKind
from agentforge.core.models import RunStatus
from agentforge.runtime.factory import run_agent
from agentforge.sandbox.docker import DockerSandbox
from agentforge.sandbox.workspace import Workspace
from agentforge.settings import Settings
from tests.conftest import scripted_config

IMAGE = os.environ.get("AGENTFORGE_TEST_SANDBOX_IMAGE", "python:3.12-slim")


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "image", "inspect", IMAGE], check=True, capture_output=True, timeout=20
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return True


pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not _docker_ready(), reason=f"docker daemon or image {IMAGE} unavailable"),
]


@pytest.fixture
async def sandbox(workspace: Workspace) -> AsyncIterator[DockerSandbox]:
    box = DockerSandbox(workspace, SandboxConfig(kind=SandboxKind.DOCKER, image=IMAGE))
    await box.start()
    yield box
    await box.close()


async def test_exec_in_workspace(sandbox: DockerSandbox, workspace: Workspace) -> None:
    (workspace.root / "sub").mkdir()
    result = await sandbox.exec(["sh", "-c", "pwd && echo hi > out.txt"], cwd="sub")
    assert result.ok, result.stderr
    assert result.stdout.strip() == "/workspace/sub"
    host_file = workspace.root / "sub" / "out.txt"
    assert host_file.read_text() == "hi\n"
    if hasattr(os, "getuid"):
        assert host_file.stat().st_uid == os.getuid()  # not root-owned


async def test_no_network(sandbox: DockerSandbox) -> None:
    result = await sandbox.exec(
        ["python3", "-c", "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)"]
    )
    assert result.exit_code != 0


async def test_root_filesystem_read_only_and_no_capabilities(sandbox: DockerSandbox) -> None:
    result = await sandbox.exec(["sh", "-c", "touch /etc/pwned"])
    assert result.exit_code != 0
    caps = await sandbox.exec(["sh", "-c", "grep CapEff /proc/self/status"])
    assert caps.stdout.split()[-1] == "0000000000000000"
    tmp = await sandbox.exec(["sh", "-c", "echo x > /tmp/ok && cat /tmp/ok"])
    assert tmp.ok


async def test_host_environment_not_visible(
    sandbox: DockerSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "host-secret-value")
    result = await sandbox.exec(["env"])
    assert "host-secret-value" not in result.stdout


async def test_command_timeout_kills(sandbox: DockerSandbox) -> None:
    result = await sandbox.exec(["sleep", "30"], timeout=1)
    assert not result.ok
    assert result.duration_ms < 15_000


async def test_pids_limit(workspace: Workspace) -> None:
    box = DockerSandbox(
        workspace, SandboxConfig(kind=SandboxKind.DOCKER, image=IMAGE, pids_limit=32)
    )
    async with box:
        result = await box.exec(
            ["sh", "-c", "for i in $(seq 1 100); do sleep 5 & done; wait"], timeout=20
        )
    assert not result.ok
    assert "cannot fork" in result.stderr.lower()


async def test_agent_run_in_docker_sandbox(settings: Settings) -> None:
    turns = [
        {
            "tool_calls": [
                {"name": "write_file", "arguments": {"path": "app.py", "content": "print(6*7)\n"}}
            ]
        },
        {"tool_calls": [{"name": "run_command", "arguments": {"command": "python3 app.py"}}]},
        {"text": "It prints 42."},
    ]
    config = scripted_config(
        turns,
        tools=["filesystem", "terminal"],
        sandbox=SandboxConfig(kind=SandboxKind.DOCKER, image=IMAGE),
    )
    from agentforge.evaluation.base import EvaluatorSpec

    run = await run_agent(
        config,
        "print 42",
        settings=settings,
        evaluators=[EvaluatorSpec(type="command", command='test "$(python3 app.py)" = 42')],
    )
    assert run.status == RunStatus.SUCCEEDED, run.error
    assert "42" in run.steps[1].tool_calls[0].output
    assert run.evaluation is not None and run.evaluation.passed
    # the container is removed after the run
    listing = subprocess.run(
        ["docker", "ps", "-a", "--filter", "label=agentforge.sandbox=1", "-q"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert listing.stdout.strip() == ""
    assert Path(run.workspace or "").joinpath("app.py").exists()


def _docker(*args: str) -> str:
    return subprocess.run(
        ["docker", *args], check=True, capture_output=True, text=True, timeout=120
    ).stdout.strip()


@pytest.fixture
def egress_setup() -> Iterator[str]:
    """internal network <-> egress proxy <-> 'outside' network with an origin server."""
    suffix = os.urandom(3).hex()
    internal, outside = f"af-int-{suffix}", f"af-out-{suffix}"
    proxy_file = Path(__file__).resolve().parents[2] / "src/agentforge/sandbox/egress_proxy.py"
    containers = [f"af-origin-{suffix}", f"af-egress-{suffix}"]
    _docker("network", "create", "--internal", internal)
    _docker("network", "create", outside)
    try:
        _docker(
            "run",
            "-d",
            "--rm",
            "--name",
            containers[0],
            "--network",
            outside,
            "--network-alias",
            "origin",
            IMAGE,
            "python3",
            "-m",
            "http.server",
            "8080",
        )
        _docker(
            "run",
            "-d",
            "--rm",
            "--name",
            containers[1],
            "--network",
            outside,
            "-v",
            f"{proxy_file}:/proxy.py:ro",
            IMAGE,
            "python3",
            "/proxy.py",
            "--allow",
            "origin",
            "--ports",
            "8080",
            "--port",
            "3128",
        )
        _docker("network", "connect", "--alias", "egress", internal, containers[1])
        time.sleep(1.5)
        yield internal
    finally:
        for name in containers:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
        for net in (internal, outside):
            subprocess.run(["docker", "network", "rm", net], capture_output=True, check=False)


async def test_egress_proxy_allows_only_listed_hosts(
    workspace: Workspace, egress_setup: str
) -> None:
    config = SandboxConfig(
        kind=SandboxKind.DOCKER, image=IMAGE, network=egress_setup, proxy="http://egress:3128"
    )
    fetch = (
        "import urllib.request,sys; print(urllib.request.urlopen(sys.argv[1], timeout=10).status)"
    )
    async with DockerSandbox(workspace, config) as box:
        allowed = await box.exec(["python3", "-c", fetch, "http://origin:8080/"], timeout=30)
        assert allowed.ok, allowed.stderr
        assert allowed.stdout.strip() == "200"
        blocked = await box.exec(["python3", "-c", fetch, "http://example.com/"], timeout=30)
        assert not blocked.ok
        assert "403" in blocked.stderr
        # bypassing the proxy fails: the internal network has no route out
        direct = await box.exec(
            [
                "python3",
                "-c",
                "import socket; socket.create_connection(('1.1.1.1', 80), timeout=5)",
            ],
            timeout=30,
        )
        assert not direct.ok
