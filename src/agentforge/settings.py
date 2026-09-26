"""Process-level settings (environment variables prefixed ``AGENTFORGE_``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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
    benchmarks_dir: Path = Field(default=Path("examples/benchmarks"))
    keep_workspaces: bool = True
    otel_enabled: bool = Field(
        default=False,
        description="Export finished runs as OpenTelemetry traces over OTLP/HTTP "
        "(configure with the standard OTEL_EXPORTER_OTLP_* variables).",
    )
    github_token_env: str = Field(
        default="GITHUB_TOKEN", description="Environment variable holding the GitHub token."
    )

    @field_validator("denied_permissions", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

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
