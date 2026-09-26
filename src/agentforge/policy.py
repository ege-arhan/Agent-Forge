"""Server-side policy for configurations submitted through the HTTP API.

Agent configs and evaluator specs sent to the API are *untrusted input*: a
caller controls provider endpoints, which environment variables are used as
credentials, tool settings and evaluator types. Without restrictions a caller
could, for example, point a provider's ``base_url`` at their own server and
name any server environment variable as the API key, exfiltrating it.

The CLI runs the operator's own files and does not apply this policy.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from agentforge.core.config import AgentConfig, ModelConfig
from agentforge.core.errors import ConfigurationError
from agentforge.evaluation.base import EvaluatorSpec
from agentforge.integrations.github.client import API_URL as GITHUB_API_URL
from agentforge.settings import Settings

# Providers whose adapters never send a server credential by default.
_KEYLESS_PROVIDERS = frozenset({"scripted", "local"})
_DEFAULT_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


class PolicyViolationError(ConfigurationError):
    code = "policy_violation"


def _host(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise PolicyViolationError(f"invalid URL '{url}'")
    return parts.hostname.lower()


class ServerPolicy:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # -------------------------------------------------------------- models
    def check_model(self, model: ModelConfig, *, where: str = "model") -> None:
        key_env = model.api_key_env or _DEFAULT_KEY_ENV.get(model.provider)
        sends_key = model.provider not in _KEYLESS_PROVIDERS or model.api_key_env is not None
        if (
            model.api_key_env is not None
            and model.api_key_env not in self.settings.allowed_key_envs
        ):
            raise PolicyViolationError(
                f"{where}.api_key_env '{model.api_key_env}' is not an allowed credential "
                "variable on this server (AGENTFORGE_ALLOWED_KEY_ENVS)"
            )
        if model.base_url and sends_key:
            host = _host(model.base_url)
            if host not in self.settings.allowed_provider_hosts:
                raise PolicyViolationError(
                    f"{where}.base_url host '{host}' is not allowed to receive the server's "
                    f"{key_env or 'provider'} credential (AGENTFORGE_ALLOWED_PROVIDER_HOSTS)"
                )
        extra = model.options.get("extra_params")
        if extra is not None and not isinstance(extra, dict):
            raise PolicyViolationError(f"{where}.options.extra_params must be an object")

    # --------------------------------------------------------------- tools
    def check_tool_settings(self, tool_settings: dict[str, dict[str, Any]]) -> None:
        http = tool_settings.get("http_request", {})
        if http.get("allow_private_networks") and not self.settings.allow_private_http:
            raise PolicyViolationError(
                "tool_settings.http_request.allow_private_networks is disabled on this server"
            )
        github = tool_settings.get("github", {})
        token_env = github.get("token_env")
        if token_env is not None and token_env not in self.settings.allowed_key_envs:
            raise PolicyViolationError(
                f"tool_settings.github.token_env '{token_env}' is not an allowed "
                "credential variable"
            )
        api_url = github.get("api_url")
        if api_url is not None and api_url.rstrip("/") != GITHUB_API_URL:
            host = _host(api_url)
            if host not in self.settings.allowed_provider_hosts:
                raise PolicyViolationError(
                    f"tool_settings.github.api_url host '{host}' is not allowed on this server"
                )
        git_env = tool_settings.get("git", {}).get("env")
        if git_env:
            raise PolicyViolationError("tool_settings.git.env cannot be set through the API")

    # --------------------------------------------------------------- agent
    def check_agent(self, config: AgentConfig) -> None:
        self.check_model(config.model)
        self.check_tool_settings(config.tool_settings)
        if config.sandbox.kind.value == "local" and not self.settings.allow_local_sandbox:
            raise PolicyViolationError(
                "the local (unisolated) sandbox is disabled on this server; use sandbox.kind=docker"
            )
        if config.sandbox.network != "none" and not self.settings.allow_sandbox_network:
            raise PolicyViolationError("sandbox networking is disabled on this server")

    # ---------------------------------------------------------- evaluators
    def check_evaluators(self, specs: list[EvaluatorSpec]) -> None:
        for spec in specs:
            if spec.type == "python" and not self.settings.allow_python_evaluators:
                raise PolicyViolationError(
                    "python evaluators (arbitrary imports) are disabled for API requests "
                    "(AGENTFORGE_ALLOW_PYTHON_EVALUATORS)"
                )
            if spec.type == "llm_judge":
                model = spec.params.get("model")
                if isinstance(model, dict):
                    try:
                        judge = ModelConfig.model_validate(model)
                    except ValueError as exc:
                        raise PolicyViolationError(f"invalid llm_judge model: {exc}") from exc
                    self.check_model(judge, where=f"evaluator '{spec.name or spec.type}'.model")
