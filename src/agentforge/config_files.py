"""Loading agent configuration files (YAML or JSON)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from agentforge.core.config import AgentConfig
from agentforge.core.errors import ConfigurationError


def load_agent_config(path: str | Path) -> AgentConfig:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"cannot read agent config {path}: {exc}") from exc
    try:
        return AgentConfig.model_validate(data)
    except ValueError as exc:
        raise ConfigurationError(f"invalid agent config {path}: {exc}") from exc


def parse_agent_config_text(text: str, *, allow_aliases: bool = True) -> AgentConfig:
    """Parse an agent configuration from YAML (or JSON, which YAML reads) text.

    ``allow_aliases=False`` rejects YAML anchors/aliases. Use it for text from
    an untrusted caller: aliases let a few hundred bytes describe a structure
    that is exponentially large once it is walked or serialised.
    """
    try:
        if not allow_aliases:
            for event in yaml.parse(text, Loader=yaml.SafeLoader):
                if isinstance(event, yaml.AliasEvent):
                    raise ConfigurationError(
                        "invalid agent config: YAML aliases (*name) are not accepted here; "
                        "write the value out"
                    )
        data = yaml.safe_load(text)
    except (ValueError, RecursionError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"cannot parse agent config: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError(
            "invalid agent config: expected a mapping with keys such as 'name' and 'model'"
        )
    try:
        return AgentConfig.model_validate(data)
    except ValueError as exc:
        raise ConfigurationError(f"invalid agent config: {exc}") from exc
