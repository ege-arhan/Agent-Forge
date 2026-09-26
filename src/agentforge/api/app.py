"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agentforge import __version__
from agentforge.api.deps import require_api_key
from agentforge.api.middleware import HardeningMiddleware
from agentforge.api.routes import agents, benchmarks, github, improvements, meta, metrics, runs
from agentforge.core.errors import (
    AgentForgeError,
    BenchmarkError,
    CapacityError,
    ConfigurationError,
    ImprovementError,
    NotFoundError,
)
from agentforge.integrations.github.client import GitHubError
from agentforge.integrations.github.workflow import GitHubWorkflowError
from agentforge.observability.logging import configure_logging
from agentforge.service import AgentForgeService
from agentforge.settings import Settings, get_settings
from agentforge.storage import Database

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level, json_format=settings.log_json)
        db = Database(settings.resolved_database_url)
        service = AgentForgeService(settings, db)
        await service.startup()
        app.state.service = service
        try:
            yield
        finally:
            await service.shutdown()
            await db.dispose()

    app = FastAPI(
        title="AgentForge API",
        version=__version__,
        description="Create, run, observe, evaluate and benchmark LLM agents.",
        lifespan=lifespan,
    )
    app.add_middleware(
        HardeningMiddleware,
        max_body_bytes=settings.max_request_bytes,
        rate_limit_per_minute=settings.rate_limit_per_minute,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": exc.message})

    @app.exception_handler(ConfigurationError)
    @app.exception_handler(BenchmarkError)
    @app.exception_handler(GitHubWorkflowError)
    async def _bad_config(request: Request, exc: AgentForgeError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": exc.message, "code": exc.code})

    @app.exception_handler(ImprovementError)
    async def _conflict(request: Request, exc: ImprovementError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": exc.message, "code": exc.code})

    @app.exception_handler(CapacityError)
    async def _capacity(request: Request, exc: CapacityError) -> JSONResponse:
        return JSONResponse(
            status_code=429, content={"detail": exc.message}, headers={"Retry-After": "30"}
        )

    @app.exception_handler(GitHubError)
    async def _github_error(request: Request, exc: GitHubError) -> JSONResponse:
        status_code = 502 if exc.status_code is None or exc.status_code >= 500 else exc.status_code
        if status_code == 401:
            status_code = 502  # upstream credential problem, not the caller's
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError) -> JSONResponse:
        if isinstance(exc, RequestValidationError):  # pragma: no cover - handled by FastAPI
            raise exc
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    protected = [Depends(require_api_key)]
    app.include_router(meta.public, prefix=API_PREFIX)
    for module in (meta, metrics, agents, runs, benchmarks, improvements, github):
        app.include_router(module.router, prefix=API_PREFIX, dependencies=protected)
    return app
