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
