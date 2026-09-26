"""Outbound HTTP requests with SSRF protection.

Every request target (including redirect targets) is resolved and rejected if
any address is private, loopback, link-local, multicast or otherwise not
globally routable, unless ``allow_private_networks`` is set. An optional host
allowlist (``allowed_hosts``; ``*.example.com`` wildcards supported) further
restricts destinations.

Known limitation: the check resolves DNS before httpx connects, so a
DNS-rebinding attacker could return a different address on the second lookup.
Run untrusted agents with sandbox networking disabled and an allowlist.
"""

from __future__ import annotations

import asyncio
import fnmatch
import ipaddress
import socket
from typing import Any, ClassVar, Literal
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import Field

from agentforge.core.errors import PermissionDeniedError, ToolError
from agentforge.tools.base import Permission, Tool, ToolContext, ToolInput, ToolOutput

MAX_REDIRECTS = 5
DEFAULT_MAX_RESPONSE_BYTES = 200_000


class HttpRequestInput(ToolInput):
    method: Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    url: str = Field(description="Absolute http(s) URL.")
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = Field(default=None, max_length=1_000_000)
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)


async def resolve_host(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def host_allowed(host: str, allowed: list[str]) -> bool:
    host = host.lower().rstrip(".")
    for raw in allowed:
        pattern = raw.lower()
        if host == pattern or fnmatch.fnmatch(host, pattern):
            return True
    return False


class HttpRequest(Tool[HttpRequestInput]):
    name = "http_request"
    description = (
        "Make an HTTP(S) request to a public host and return status, headers and body text. "
        "Private and internal network addresses are blocked."
    )
    input_model = HttpRequestInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.NETWORK})
    timeout_seconds = 150.0

    #: Overridable in tests.
    transport: ClassVar[httpx.AsyncBaseTransport | None] = None
    resolver = staticmethod(resolve_host)

    async def _check_url(self, url: str, settings: dict[str, Any]) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise ToolError("only http and https URLs are allowed")
        host = parts.hostname
        if not host:
            raise ToolError("URL has no host")
        allowed_hosts: list[str] = list(settings.get("allowed_hosts", []))
        if allowed_hosts and not host_allowed(host, allowed_hosts):
            raise PermissionDeniedError(f"host '{host}' is not in the allowed_hosts list")
        if settings.get("allow_private_networks", False):
            return
        port = parts.port or (443 if parts.scheme == "https" else 80)
        try:
            addresses = await self.resolver(host, port)
        except OSError as exc:
            raise ToolError(f"could not resolve host '{host}'") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address.split("%")[0])
            if not ip.is_global:
                raise PermissionDeniedError(
                    f"host '{host}' resolves to a non-public address; request blocked"
                )

    async def run(self, args: HttpRequestInput, ctx: ToolContext) -> ToolOutput:
        settings: dict[str, Any] = ctx.settings.get(self.name, {})
        max_bytes = int(settings.get("max_response_bytes", DEFAULT_MAX_RESPONSE_BYTES))
        url = args.url
        method = args.method
        body = args.body
        async with httpx.AsyncClient(
            transport=self.transport, follow_redirects=False, timeout=args.timeout_seconds
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                await self._check_url(url, settings)
                try:
                    async with client.stream(
                        method, url, headers=args.headers, content=body
                    ) as response:
                        if response.is_redirect and "location" in response.headers:
                            url = urljoin(url, response.headers["location"])
                            if response.status_code in (301, 302, 303):
                                method, body = "GET", None
                            continue
                        chunks: list[bytes] = []
                        size = 0
                        truncated = False
                        async for chunk in response.aiter_bytes():
                            if size + len(chunk) > max_bytes:
                                chunks.append(chunk[: max_bytes - size])
                                truncated = True
                                break
                            chunks.append(chunk)
                            size += len(chunk)
                        text = b"".join(chunks).decode(response.encoding or "utf-8", "replace")
                        headers = "\n".join(
                            f"{k}: {v}"
                            for k, v in response.headers.items()
                            if k.lower() in ("content-type", "content-length", "location", "date")
                        )
                        content = f"HTTP {response.status_code}\n{headers}\n\n{text}"
                        if truncated:
                            content += f"\n[body truncated at {max_bytes} bytes]"
                        return ToolOutput(
                            content=content,
                            is_error=response.status_code >= 400,
                            data={"status_code": response.status_code},
                        )
                except httpx.HTTPError as exc:
                    raise ToolError(f"request failed: {type(exc).__name__}: {exc}") from exc
        raise ToolError(f"too many redirects (>{MAX_REDIRECTS})")


HTTP_TOOLS: list[type[Tool[Any]]] = [HttpRequest]
