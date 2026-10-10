"""Provider factory and plugin registration."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib.metadata import entry_points

from agentforge.core.config import ModelConfig
from agentforge.core.errors import ConfigurationError
from agentforge.llm.base import LLMProvider

ProviderFactory = Callable[[ModelConfig, Mapping[str, str]], LLMProvider]


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    description: str
    api_key_env: str | None
    requires_model: bool


def _scripted(config: ModelConfig, env: Mapping[str, str]) -> LLMProvider:
    from agentforge.llm.scripted import ScriptedProvider

    return ScriptedProvider.from_options(config.options)


def _anthropic(config: ModelConfig, env: Mapping[str, str]) -> LLMProvider:
    from agentforge.llm.anthropic import AnthropicProvider

    key = env.get(config.api_key_env or "ANTHROPIC_API_KEY")
    return AnthropicProvider(
        api_key=key,
        base_url=config.base_url,
        extra_params=config.options.get("extra_params"),
    )


def _gemini(config: ModelConfig, env: Mapping[str, str]) -> LLMProvider:
    from agentforge.llm.gemini import GeminiProvider

    key = env.get(config.api_key_env or "GEMINI_API_KEY")
    return GeminiProvider(
        api_key=key,
        base_url=config.base_url,
        extra_params=config.options.get("extra_params"),
    )


def _openai_compat(preset_name: str) -> ProviderFactory:
    def factory(config: ModelConfig, env: Mapping[str, str]) -> LLMProvider:
        from agentforge.llm.openai_compat import PRESETS, OpenAICompatibleProvider

        preset = PRESETS[preset_name]
        auth = str(config.options.get("auth", "api_key"))
        key_env = config.api_key_env or preset.api_key_env
        # In proxy mode the key is never read, even when the variable exists.
        key = env.get(key_env) if key_env and auth != "proxy" else None
        return OpenAICompatibleProvider(
            preset,
            api_key=key,
            base_url=config.base_url,
            extra_params=config.options.get("extra_params"),
            auth=auth,
        )

    return factory


_FACTORIES: dict[str, ProviderFactory] = {
    "scripted": _scripted,
    "anthropic": _anthropic,
    "openai": _openai_compat("openai"),
    "openrouter": _openai_compat("openrouter"),
    "gemini": _gemini,
    "opencode-go": _openai_compat("opencode-go"),
    "local": _openai_compat("local"),
}

_INFO: dict[str, ProviderInfo] = {
    "scripted": ProviderInfo(
        "scripted", "Deterministic replay of scripted turns (testing, demos).", None, False
    ),
    "anthropic": ProviderInfo(
        "anthropic", "Anthropic Messages API (Claude models).", "ANTHROPIC_API_KEY", False
    ),
    "openai": ProviderInfo("openai", "OpenAI Chat Completions API.", "OPENAI_API_KEY", True),
    "openrouter": ProviderInfo(
        "openrouter", "OpenRouter (OpenAI-compatible gateway).", "OPENROUTER_API_KEY", True
    ),
    "gemini": ProviderInfo(
        "gemini", "Google Gemini native API (generateContent).", "GEMINI_API_KEY", True
    ),
    "opencode-go": ProviderInfo(
        "opencode-go",
        "OpenCode Go subscription models via an OpenAI-compatible endpoint; set model.base_url. "
        "Sends x-opencode-session (the run id); options.auth: proxy for proxy-injected keys.",
        "OPENCODE_API_KEY",
        True,
    ),
    "local": ProviderInfo(
        "local",
        "Local OpenAI-compatible server (Ollama, vLLM, LM Studio); set model.base_url.",
        None,
        True,
    ),
}

_plugins_loaded = False


def register_provider(
    name: str, factory: ProviderFactory, *, description: str = "", api_key_env: str | None = None
) -> None:
    """Register a custom provider factory (also available via the
    ``agentforge.providers`` entry-point group)."""
    _FACTORIES[name] = factory
    _INFO[name] = ProviderInfo(name, description or f"Custom provider '{name}'.", api_key_env, True)


def _load_plugins() -> None:
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    for ep in entry_points(group="agentforge.providers"):
        if ep.name not in _FACTORIES:
            register_provider(ep.name, ep.load())


def available_providers() -> list[ProviderInfo]:
    _load_plugins()
    return [_INFO[name] for name in sorted(_FACTORIES)]


def create_provider(config: ModelConfig, env: Mapping[str, str] | None = None) -> LLMProvider:
    _load_plugins()
    factory = _FACTORIES.get(config.provider)
    if factory is None:
        known = ", ".join(sorted(_FACTORIES))
        raise ConfigurationError(f"unknown provider '{config.provider}' (known: {known})")
    return factory(config, env if env is not None else os.environ)
