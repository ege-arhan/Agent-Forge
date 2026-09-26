"""Minimal allowlisting HTTP(S) egress proxy for sandboxes.

Sandboxes attached to an *internal* Docker network cannot reach the outside
world directly; pointing their ``HTTP(S)_PROXY`` at this proxy (attached to
both the internal network and a routed network) gives them access to exactly
the allowlisted hosts - e.g. a package index - and nothing else.

Supports ``CONNECT host:port`` (HTTPS, tunnelled without inspection) and
absolute-URI plain-HTTP requests. Everything else is refused with 403/400.

Run: ``python -m agentforge.sandbox.egress_proxy --allow pypi.org,files.pythonhosted.org``
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import fnmatch
import logging
from urllib.parse import urlsplit

logger = logging.getLogger("agentforge.egress")

MAX_HEADER_BYTES = 64 * 1024
DEFAULT_PORTS = frozenset({80, 443})


def host_allowed(host: str, patterns: list[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == p.lower() or fnmatch.fnmatch(host, p.lower()) for p in patterns)


class EgressProxy:
    def __init__(
        self,
        allow: list[str],
        *,
        ports: frozenset[int] = DEFAULT_PORTS,
        connect_timeout: float = 10.0,
    ) -> None:
        self.allow = allow
        self.ports = ports
        self.connect_timeout = connect_timeout

    def permitted(self, host: str, port: int) -> bool:
        return port in self.ports and host_allowed(host, self.allow)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            writer.close()
            return
        try:
            request_line, *header_lines = head.decode("latin-1").split("\r\n")
            method, target, version = request_line.split(" ", 2)
        except ValueError:
            await self._reply(writer, 400, "Bad Request")
            return

        if method.upper() == "CONNECT":
            host, _, port_text = target.rpartition(":")
            host = host.strip("[]")
            port = int(port_text) if port_text.isdigit() else 443
            await self._tunnel(reader, writer, host, port)
            return

        url = urlsplit(target)
        if url.scheme != "http" or not url.hostname:
            await self._reply(writer, 400, "Bad Request")
            return
        port = url.port or 80
        if not self.permitted(url.hostname, port):
            logger.info("denied %s %s", method, url.hostname)
            await self._reply(writer, 403, "Forbidden")
            return
        path = url.path or "/"
        if url.query:
            path += f"?{url.query}"
        kept = [
            line
            for line in header_lines
            if line and not line.lower().startswith(("proxy-", "connection:"))
        ]
        forward = (
            f"{method} {path} {version}\r\n" + "\r\n".join(kept) + "\r\nConnection: close\r\n\r\n"
        )
        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(url.hostname, port), timeout=self.connect_timeout
            )
        except (OSError, TimeoutError):
            await self._reply(writer, 502, "Bad Gateway")
            return
        logger.info("allowed %s http://%s:%d", method, url.hostname, port)
        up_writer.write(forward.encode("latin-1"))
        await self._pipe_both(reader, writer, up_reader, up_writer)

    async def _tunnel(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, host: str, port: int
    ) -> None:
        if not self.permitted(host, port):
            logger.info("denied CONNECT %s:%d", host, port)
            await self._reply(writer, 403, "Forbidden")
            return
        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=self.connect_timeout
            )
        except (OSError, TimeoutError):
            await self._reply(writer, 502, "Bad Gateway")
            return
        logger.info("allowed CONNECT %s:%d", host, port)
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await self._pipe_both(reader, writer, up_reader, up_writer)

    async def _pipe_both(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        up_reader: asyncio.StreamReader,
        up_writer: asyncio.StreamWriter,
    ) -> None:
        async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while chunk := await src.read(65_536):
                    dst.write(chunk)
                    await dst.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                with contextlib.suppress(Exception):
                    dst.close()

        await asyncio.gather(pipe(client_reader, up_writer), pipe(up_reader, client_writer))

    @staticmethod
    async def _reply(writer: asyncio.StreamWriter, status: int, reason: str) -> None:
        body = f"{status} {reason}\n".encode()
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\nContent-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n".encode()
            + body
        )
        with contextlib.suppress(ConnectionError, OSError):
            await writer.drain()
        writer.close()

    async def serve(self, host: str, port: int) -> asyncio.Server:
        return await asyncio.start_server(self.handle, host, port, limit=MAX_HEADER_BYTES)


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - thin CLI wrapper
    parser = argparse.ArgumentParser(description="Allowlisting egress proxy for sandboxes")
    parser.add_argument("--allow", required=True, help="comma-separated hosts (*.example.com ok)")
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104 - listens on the sandbox network
    parser.add_argument("--port", type=int, default=3128)
    parser.add_argument("--ports", default="80,443", help="allowed destination ports")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    proxy = EgressProxy(
        [h.strip() for h in args.allow.split(",") if h.strip()],
        ports=frozenset(int(p) for p in args.ports.split(",")),
    )

    async def run() -> None:
        server = await proxy.serve(args.host, args.port)
        logger.info("egress proxy on %s:%d allowing %s", args.host, args.port, proxy.allow)
        async with server:
            await server.serve_forever()

    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    main()
