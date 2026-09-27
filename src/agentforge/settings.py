"""Process-level settings (environment variables prefixed ``AGENTFORGE_``)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agentforge.tools.base import Permission


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTFORGE_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default=Path(".agentforge"))
    database_url: str | None = Field(
        default=None, description="SQLAlchemy async URL; defaults to SQLite under data_dir."
    )
    api_key: str | None = Field(
        default=None, description="If set, the HTTP API requires 'Authorization: Bearer <key>'."
    )
    allow_local_sandbox: bool = Field(
        default=True,
        description="Allow agents to use the unisolated local sandbox. Disable on shared servers.",
    )
    denied_permissions: list[Permission] = Field(default_factory=list)
    max_concurrent_runs: int = Field(default=4, ge=1, le=256)
    log_level: str = "INFO"
    log_json: bool = False
    pricing_file: Path | None = None
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    benchmarks_dir: str = Field(
        default=os.pathsep.join(["examples/benchmarks", "dogfood/benchmarks"]),
        description="Directories with benchmark suites, separated by the OS path separator.",
    )
    keep_workspaces: bool = True
    otel_enabled: bool = Field(
        default=False,
        description="Export finished runs as OpenTelemetry traces over OTLP/HTTP "
        "(configure with the standard OTEL_EXPORTER_OTLP_* variables).",
    )
    # --- API policy (see agentforge/policy.py and SECURITY.md) ---
    allowed_key_envs: list[str] = Field(
        default_factory=lambda: [
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "GEMINI_API_KEY",
            "GITHUB_TOKEN",
        ],
        description="Environment variables API-submitted configs may use as credentials.",
    )
    allowed_provider_hosts: list[str] = Field(
        default_factory=list,
        description="Hosts that API-submitted configs may send credentials to via base_url.",
    )
    allow_private_http: bool = Field(
        default=False, description="Allow API configs to let the HTTP tool reach private networks."
    )
    allow_python_evaluators: bool = Field(
        default=False, description="Allow 'python' evaluators (arbitrary imports) via the API."
    )
    allow_sandbox_network: bool = Field(
        default=False,
        description="Allow API configs to use sandbox.network 'bridge' (unrestricted egress).",
    )
    allowed_sandbox_networks: list[str] = Field(
        default_factory=list,
        description="Operator-created Docker networks API configs may attach sandboxes to "
        "(e.g. an internal network behind the egress proxy).",
    )
    allowed_sandbox_runtimes: list[str] = Field(
        default_factory=lambda: ["runc", "runsc"],
        description="Docker runtimes API configs may request.",
    )
    max_request_bytes: int = Field(default=1_000_000, ge=1_024)
    rate_limit_per_minute: int = Field(
        default=120, ge=0, description="Mutating API requests per client per minute (0 = off)."
    )
    max_queued_runs: int = Field(
        default=100, ge=1, description="Background tasks accepted beyond which the API returns 429."
    )
    github_token_env: str = Field(
        default="GITHUB_TOKEN", description="Environment variable holding the GitHub token."
    )

    @field_validator(
        "denied_permissions",
        "cors_origins",
        "allowed_key_envs",
        "allowed_provider_hosts",
        "allowed_sandbox_networks",
        "allowed_sandbox_runtimes",
        mode="before",
    )
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("benchmarks_dir", mode="before")
    @classmethod
    def _join_dirs(cls, value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, list | tuple):
            return os.pathsep.join(str(v) for v in value)
        return value

    @property
    def benchmark_dirs(self) -> list[Path]:
        return [Path(p) for p in self.benchmarks_dir.split(os.pathsep) if p.strip()]

    @property
    def workspaces_dir(self) -> Path:
        return self.data_dir / "workspaces"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{(self.data_dir / 'agentforge.db').resolve()}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
