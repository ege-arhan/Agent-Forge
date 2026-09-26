"""HTTP hardening: body size limit, per-client rate limit, security headers."""

from __future__ import annotations

import hashlib
import time
from collections import deque
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def client_identity(request: Request) -> str:
    """Rate-limit/audit key: a fingerprint of the bearer token, else the client IP."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        digest = hashlib.sha256(header[7:].encode()).hexdigest()[:12]
        return f"key:{digest}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


class SlidingWindowLimiter:
    """In-process sliding-window limiter (per client, per minute)."""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str, now: float | None = None) -> float | None:
        """Record a hit; return seconds to wait if the limit is exceeded."""
        if self.limit <= 0:
            return None
        now = time.monotonic() if now is None else now
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(0.0, self.window - (now - hits[0]))
        hits.append(now)
        if len(self._hits) > 10_000:  # bound memory: drop idle clients
            for idle in [k for k, v in self._hits.items() if not v]:
                self._hits.pop(idle, None)
        return None


class HardeningMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, max_body_bytes: int, rate_limit_per_minute: int) -> None:
        super().__init__(app)
        self.max_body_bytes = max_body_bytes
        self.limiter = SlidingWindowLimiter(rate_limit_per_minute)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in MUTATING:
            length = request.headers.get("content-length")
            if length is not None and length.isdigit() and int(length) > self.max_body_bytes:
                return JSONResponse(status_code=413, content={"detail": "request body too large"})
            body = await request.body()  # cached by Starlette for the endpoint
            if len(body) > self.max_body_bytes:
                return JSONResponse(status_code=413, content={"detail": "request body too large"})
            wait = self.limiter.check(client_identity(request))
            if wait is not None:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "rate limit exceeded"},
                    headers={"Retry-After": str(int(wait) + 1)},
                )
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response
