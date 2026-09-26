from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from agentforge.core.config import SandboxConfig
from agentforge.sandbox.docker import build_run_args
from agentforge.sandbox.egress_proxy import EgressProxy, host_allowed
from agentforge.sandbox.workspace import Workspace


async def _origin(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    await reader.readuntil(b"\r\n\r\n")
    body = b"hello from origin"
    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))
    await writer.drain()
    writer.close()


@pytest.fixture
async def servers() -> AsyncIterator[tuple[int, int]]:
    origin = await asyncio.start_server(_origin, "127.0.0.1", 0)
    origin_port = origin.sockets[0].getsockname()[1]
    proxy = EgressProxy(["127.0.0.1"], ports=frozenset({origin_port}))
    proxy_server = await proxy.serve("127.0.0.1", 0)
    proxy_port = proxy_server.sockets[0].getsockname()[1]
    yield origin_port, proxy_port
    proxy_server.close()
    origin.close()


async def _request(proxy_port: int, raw: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.write(raw)
    await writer.drain()
    data = await asyncio.wait_for(reader.read(), timeout=5)
    writer.close()
    return data


def test_host_allowlist() -> None:
    assert host_allowed("pypi.org", ["pypi.org"])
    assert host_allowed("files.pythonhosted.org", ["*.pythonhosted.org"])
    assert not host_allowed("evil.org", ["pypi.org"])


async def test_plain_http_allowed_and_denied(servers: tuple[int, int]) -> None:
    origin_port, proxy_port = servers
    ok = await _request(
        proxy_port, f"GET http://127.0.0.1:{origin_port}/x HTTP/1.1\r\nHost: a\r\n\r\n".encode()
    )
    assert ok.startswith(b"HTTP/1.1 200") and b"hello from origin" in ok
    denied = await _request(proxy_port, b"GET http://evil.example/ HTTP/1.1\r\nHost: e\r\n\r\n")
    assert denied.startswith(b"HTTP/1.1 403")
    bad = await _request(proxy_port, b"GET /relative HTTP/1.1\r\n\r\n")
    assert bad.startswith(b"HTTP/1.1 400")


async def test_connect_tunnel_allowed_and_denied(servers: tuple[int, int]) -> None:
    origin_port, proxy_port = servers
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.write(f"CONNECT 127.0.0.1:{origin_port} HTTP/1.1\r\n\r\n".encode())
    await writer.drain()
    status = await reader.readuntil(b"\r\n\r\n")
    assert status.startswith(b"HTTP/1.1 200")
    writer.write(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")  # traffic flows through the tunnel
    await writer.drain()
    assert b"hello from origin" in await asyncio.wait_for(reader.read(), timeout=5)
    writer.close()

    denied = await _request(proxy_port, b"CONNECT evil.example:443 HTTP/1.1\r\n\r\n")
    assert denied.startswith(b"HTTP/1.1 403")
    wrong_port = await _request(proxy_port, b"CONNECT 127.0.0.1:22 HTTP/1.1\r\n\r\n")
    assert wrong_port.startswith(b"HTTP/1.1 403")


def test_sandbox_config_network_runtime_proxy(workspace: Workspace) -> None:
    config = SandboxConfig(
        kind="docker", network="agentforge-egress", runtime="runsc", proxy="http://egress:3128"
    )
    args = build_run_args(config, workspace, "c", None)
    assert args[args.index("--network") + 1] == "agentforge-egress"
    assert args[args.index("--runtime") + 1] == "runsc"
    assert "HTTPS_PROXY=http://egress:3128" in args
    for bad in [{"network": "bad name"}, {"runtime": "--privileged"}, {"proxy": "http://x/; rm"}]:
        with pytest.raises(ValueError, match="must"):
            SandboxConfig(**bad)  # type: ignore[arg-type]
