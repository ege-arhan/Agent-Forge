from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentforge.core.config import _KNOWN_PERMISSIONS, AgentConfig, ApprovalPolicy, ModelConfig
from agentforge.core.ids import new_id
from agentforge.core.models import RunStatus, TokenUsage
from agentforge.tools.base import Permission


def test_new_id_is_prefixed_and_unique() -> None:
    ids = {new_id("run") for _ in range(1000)}
    assert len(ids) == 1000
    assert all(i.startswith("run_") for i in ids)


def test_ids_sort_by_creation_time() -> None:
    first = new_id("x")
    second = new_id("x")
    assert first[:14] <= second[:14]


@pytest.mark.parametrize("name", ["ok", "agent-1", "a.b_c", "X" * 64])
def test_agent_name_valid(name: str) -> None:
    AgentConfig(name=name, model=ModelConfig(provider="scripted"))


@pytest.mark.parametrize("name", ["", "-bad", "has space", "x" * 65, "../etc"])
def test_agent_name_invalid(name: str) -> None:
    with pytest.raises(ValidationError):
        AgentConfig(name=name, model=ModelConfig(provider="scripted"))


def test_agent_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(
            {"name": "a", "model": {"provider": "scripted"}, "unknown_field": 1}
        )


def test_agent_config_roundtrip() -> None:
    config = AgentConfig(name="a", model=ModelConfig(provider="anthropic", model="claude-opus-5"))
    assert AgentConfig.model_validate(config.model_dump(mode="json")) == config


def test_terminal_statuses() -> None:
    assert RunStatus.SUCCEEDED.is_terminal
    assert RunStatus.TIMED_OUT.is_terminal
    assert not RunStatus.RUNNING.is_terminal


def test_known_permissions_match_the_tool_permission_enum() -> None:
    # core/config.py cannot import agentforge.tools.base.Permission (it would be a circular
    # import), so approval.require_for is validated against a duplicated set of literal
    # values. This test fails fast if the two ever drift apart.
    assert {p.value for p in Permission} == _KNOWN_PERMISSIONS


def test_approval_policy_accepts_known_permissions() -> None:
    policy = ApprovalPolicy(require_for={"fs:write", "network"})
    assert policy.require_for == {"fs:write", "network"}


def test_approval_policy_rejects_unknown_permission() -> None:
    with pytest.raises(ValidationError):
        ApprovalPolicy(require_for={"fs:write", "not-a-permission"})


def test_agent_config_default_approval_policy_is_empty() -> None:
    config = AgentConfig(name="a", model=ModelConfig(provider="scripted"))
    assert config.approval.require_for == frozenset()
    assert config.approval.timeout_seconds == 3600.0


def test_token_usage_add() -> None:
    usage = TokenUsage(input_tokens=1, output_tokens=2)
    usage.add(TokenUsage(input_tokens=10, output_tokens=20, cache_read_tokens=5))
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens) == (11, 22, 5)
    assert usage.total_tokens == 33
