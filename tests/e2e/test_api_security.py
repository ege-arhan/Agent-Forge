"""API hardening: config policy, body limits, rate limits, capacity, headers, audit."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentforge.api.app import create_app
from agentforge.api.middleware import SlidingWindowLimiter
from agentforge.core.config import AgentConfig, ModelConfig
from agentforge.evaluation.base import EvaluatorSpec
from agentforge.policy import PolicyViolationError, ServerPolicy
from agentforge.settings import Settings
from tests.e2e.test_api import demo_config, terminal, wait_for

pytestmark = pytest.mark.e2e

API = "/api/v1"


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def with_model(**model: Any) -> dict[str, Any]:
    config = demo_config()
    config["model"] = {"provider": "anthropic", "model": "claude-opus-5", **model}
    return config


# ------------------------------------------------------------------ policy
@pytest.mark.parametrize(
    ("config", "fragment"),
    [
        # exfiltrate the server's key to an attacker-controlled endpoint
        (with_model(base_url="https://attacker.example/v1"), "base_url host"),
        # use an arbitrary server secret as the "API key"
        (with_model(api_key_env="AGENTFORGE_API_KEY"), "api_key_env"),
        (
            {**demo_config(), "tool_settings": {"http_request": {"allow_private_networks": True}}},
            "allow_private_networks",
        ),
        (
            {**demo_config(), "tool_settings": {"github": {"api_url": "https://evil.example/api"}}},
            "api_url",
        ),
        (
            {**demo_config(), "tool_settings": {"github": {"token_env": "POSTGRES_PASSWORD"}}},
            "token_env",
        ),
        ({**demo_config(), "tool_settings": {"git": {"env": {"GIT_SSH_COMMAND": "x"}}}}, "git.env"),
        ({**demo_config(), "sandbox": {"kind": "docker", "network": "bridge"}}, "networking"),
    ],
)
def test_unsafe_configs_rejected(client: TestClient, config: dict[str, Any], fragment: str) -> None:
    for path, body in [
        ("/agents", config),
        ("/runs", {"goal": "x", "config": config}),
        ("/benchmarks/runs", {"suite_id": "starter", "config": config}),
    ]:
        response = client.post(f"{API}{path}", json=body)
        assert response.status_code == 400, (path, response.text)
        assert fragment in response.json()["detail"]
        assert response.json()["code"] == "policy_violation"


def test_unsafe_experiment_variant_rejected(client: TestClient) -> None:
    response = client.post(
        f"{API}/experiments",
        json={
            "name": "x",
            "suite_id": "starter",
            "base_config": demo_config(),
            "variants": [
                {"name": "ok"},
                {
                    "name": "evil",
                    "overrides": {
                        "model": {
                            "provider": "openai",
                            "model": "m",
                            "base_url": "https://evil.example/v1",
                        }
                    },
                },
            ],
        },
    )
    assert response.status_code == 400
    assert "base_url" in response.json()["detail"]


@pytest.mark.parametrize(
    ("spec", "fragment"),
    [
        ({"type": "python", "class": "os:system"}, "python evaluators"),
        (
            {
                "type": "llm_judge",
                "rubric": "r",
                "model": {
                    "provider": "openai",
                    "model": "m",
                    "base_url": "https://evil.example/v1",
                },
            },
            "base_url",
        ),
    ],
)
def test_unsafe_evaluators_rejected(
    client: TestClient, spec: dict[str, Any], fragment: str
) -> None:
    response = client.post(
        f"{API}/runs", json={"goal": "x", "config": demo_config(), "evaluators": [spec]}
    )
    assert response.status_code == 400
    assert fragment in response.json()["detail"]


def test_policy_allows_configured_exceptions(settings: Settings) -> None:
    policy = ServerPolicy(settings)
    # local servers receive no server credential by default
    policy.check_model(
        ModelConfig(provider="local", model="m", base_url="http://10.0.0.5:11434/v1")
    )
    # but naming a key for a local server requires an allowed host
    with pytest.raises(PolicyViolationError):
        policy.check_model(
            ModelConfig(
                provider="local",
                model="m",
                base_url="http://10.0.0.5/v1",
                api_key_env="OPENAI_API_KEY",
            )
        )
    settings.allowed_provider_hosts = ["gateway.internal"]
    policy.check_model(
        ModelConfig(provider="openai", model="m", base_url="https://gateway.internal/v1")
    )
    settings.allow_python_evaluators = True
    policy.check_evaluators([EvaluatorSpec(type="python", **{"class": "x:Y"})])
    settings.allow_local_sandbox = False
    with pytest.raises(PolicyViolationError, match="local"):
        policy.check_agent(AgentConfig.model_validate(demo_config()))


def test_rerun_rechecks_policy(client: TestClient, settings: Settings) -> None:
    run_id = client.post(
        f"{API}/runs", json={"goal": "Create hello.txt", "config": demo_config()}
    ).json()["id"]
    wait_for(client, f"{API}/runs/{run_id}", terminal)
    settings.allow_local_sandbox = False  # operator tightens policy afterwards
    response = client.post(f"{API}/runs/{run_id}/rerun")
    assert response.status_code == 400


# ------------------------------------------------------ transport controls
def test_security_headers(client: TestClient) -> None:
    response = client.get(f"{API}/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_request_body_limit(settings: Settings) -> None:
    settings.max_request_bytes = 2_000
    with TestClient(create_app(settings)) as client:
        response = client.post(f"{API}/runs", json={"goal": "x" * 5_000, "config": demo_config()})
        assert response.status_code == 413


def test_rate_limit(settings: Settings) -> None:
    settings.rate_limit_per_minute = 3
    with TestClient(create_app(settings)) as client:
        codes = [client.post(f"{API}/agents", json={"bad": 1}).status_code for _ in range(5)]
        assert codes[:3] == [422, 422, 422]
        assert codes[3:] == [429, 429]
        limited = client.post(f"{API}/agents", json={})
        assert int(limited.headers["retry-after"]) >= 1
        assert client.get(f"{API}/agents").status_code == 200  # reads are not limited


def test_sliding_window_limiter() -> None:
    limiter = SlidingWindowLimiter(2, window_seconds=10)
    assert limiter.check("a", now=0) is None
    assert limiter.check("a", now=1) is None
    assert limiter.check("a", now=2) == pytest.approx(8)
    assert limiter.check("b", now=2) is None  # per client
    assert limiter.check("a", now=10.5) is None  # window slid
    assert SlidingWindowLimiter(0).check("a") is None  # disabled


def test_capacity_limit(settings: Settings) -> None:
    settings.max_queued_runs = 1
    config = demo_config()
    config["model"]["options"] = {
        "turns": [{"tool_calls": [{"name": "run_command", "arguments": {"command": "sleep 20"}}]}]
    }
    with TestClient(create_app(settings)) as client:
        first = client.post(f"{API}/runs", json={"goal": "sleep", "config": config})
        assert first.status_code == 202
        second = client.post(f"{API}/runs", json={"goal": "sleep", "config": config})
        assert second.status_code == 429
        assert second.headers["retry-after"] == "30"
        client.post(f"{API}/runs/{first.json()['id']}/cancel")


def test_audit_log(client: TestClient) -> None:
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Capture()
    audit_logger = logging.getLogger("agentforge.audit")
    audit_logger.addHandler(handler)
    try:
        agent = client.post(
            f"{API}/agents", json=demo_config(), headers={"Authorization": "Bearer abc"}
        )
        assert agent.status_code == 201
        time.sleep(0.01)
    finally:
        audit_logger.removeHandler(handler)
    record = next(r for r in records if getattr(r, "action", None) == "agent.create")
    assert record.client.startswith("key:") and "abc" not in record.client  # type: ignore[attr-defined]
    assert record.details["name"] == "scripted-demo"  # type: ignore[attr-defined]


def test_sandbox_network_and_runtime_policy(settings: Settings) -> None:
    policy = ServerPolicy(settings)

    def config(**sandbox: Any) -> AgentConfig:
        data = demo_config()
        data["sandbox"] = {"kind": "docker", **sandbox}
        return AgentConfig.model_validate(data)

    with pytest.raises(PolicyViolationError, match="not allowed"):
        policy.check_agent(config(network="agentforge-egress"))
    settings.allowed_sandbox_networks = ["agentforge-egress"]
    policy.check_agent(config(network="agentforge-egress", proxy="http://egress:3128"))
    policy.check_agent(config(runtime="runsc"))
    with pytest.raises(PolicyViolationError, match="runtime"):
        policy.check_agent(config(runtime="custom-runtime"))
