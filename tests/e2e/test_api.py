"""End-to-end tests through the HTTP API (offline, scripted provider)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from agentforge.api.app import create_app
from agentforge.settings import Settings

pytestmark = pytest.mark.e2e

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
API = "/api/v1"


def demo_config() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((EXAMPLES / "agents" / "scripted-demo.yaml").read_text())
    return data


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def wait_for(client: TestClient, path: str, done: Any, timeout: float = 20.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(path).json()
        if done(body):
            return body
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {path}: {body}")


def terminal(body: dict[str, Any]) -> bool:
    return body["status"] in {"succeeded", "failed", "cancelled", "timed_out"}


def test_health_and_capabilities(client: TestClient) -> None:
    health = client.get(f"{API}/health").json()
    assert health["status"] == "ok" and health["database"] == "ok"
    providers = {p["name"] for p in client.get(f"{API}/providers").json()}
    assert {"anthropic", "openai", "gemini", "openrouter", "local"} <= providers
    tools = client.get(f"{API}/tools").json()
    assert "filesystem" in tools["toolsets"]
    evaluators = {e["type"] for e in client.get(f"{API}/evaluators").json()}
    assert "command" in evaluators


def test_agent_lifecycle_and_run(client: TestClient) -> None:
    created = client.post(f"{API}/agents", json=demo_config())
    assert created.status_code == 201, created.text
    agent = created.json()
    assert client.post(f"{API}/agents", json=demo_config()).status_code == 409

    response = client.post(
        f"{API}/runs",
        json={
            "agent_id": agent["id"],
            "goal": "Create a file named hello.txt containing exactly the text: Hello, AgentForge!",
            "evaluators": [
                {"type": "file_contains", "path": "hello.txt", "text": "Hello, AgentForge!"}
            ],
        },
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    run = wait_for(client, f"{API}/runs/{run_id}", terminal)
    assert run["status"] == "succeeded"
    assert run["evaluation"]["passed"] is True
    assert run["steps"][0]["tool_calls"][0]["tool"] == "write_file"

    listing = client.get(f"{API}/runs", params={"agent_id": agent["id"]}).json()
    assert listing["total"] == 1 and listing["items"][0]["passed"] is True

    stats = client.get(f"{API}/stats").json()
    assert stats["total_runs"] == 1 and stats["evaluation_pass_rate"] == 1.0

    rerun = client.post(f"{API}/runs/{run_id}/rerun")
    assert rerun.status_code == 202
    rerun_body = wait_for(client, f"{API}/runs/{rerun.json()['id']}", terminal)
    assert rerun_body["parent_run_id"] == run_id
    assert rerun_body["evaluation"]["passed"] is True  # evaluators reproduced

    updated = client.put(f"{API}/agents/{agent['id']}", json={**demo_config(), "description": "v2"})
    assert updated.json()["version"] == 2
    assert client.delete(f"{API}/agents/{agent['id']}").status_code == 204
    assert client.get(f"{API}/agents/{agent['id']}").status_code == 404


def test_run_validation_errors(client: TestClient) -> None:
    assert client.post(f"{API}/runs", json={"goal": "x"}).status_code == 422
    assert (
        client.post(f"{API}/runs", json={"goal": "x", "agent_id": "agt_missing"}).status_code == 404
    )
    bad = {**demo_config(), "tools": ["no_such_tool"]}
    assert client.post(f"{API}/runs", json={"goal": "x", "config": bad}).status_code == 400
    assert client.get(f"{API}/runs/run_missing").status_code == 404


def test_cancel_long_running_run(client: TestClient) -> None:
    config = demo_config()
    config["model"]["options"] = {
        "turns": [{"tool_calls": [{"name": "run_command", "arguments": {"command": "sleep 30"}}]}]
    }
    run_id = client.post(f"{API}/runs", json={"goal": "sleep", "config": config}).json()["id"]
    wait_for(client, f"{API}/runs/{run_id}", lambda b: b["status"] == "running")
    started = time.monotonic()
    cancelled = client.post(f"{API}/runs/{run_id}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert time.monotonic() - started < 15


def test_event_stream_for_finished_run(client: TestClient) -> None:
    run_id = client.post(
        f"{API}/runs", json={"goal": "Create hello.txt", "config": demo_config()}
    ).json()["id"]
    wait_for(client, f"{API}/runs/{run_id}", terminal)
    with client.stream("GET", f"{API}/runs/{run_id}/events") as stream:
        body = "".join(stream.iter_text())
    assert "event: snapshot" in body


def test_benchmark_and_experiment_via_api(client: TestClient) -> None:
    suites = client.get(f"{API}/benchmarks/suites").json()
    assert "starter" in {s["id"] for s in suites}

    bench = client.post(
        f"{API}/benchmarks/runs",
        json={
            "suite_id": "starter",
            "config": demo_config(),
            "task_ids": ["create-greeting", "count-csv-rows"],
        },
    )
    assert bench.status_code == 202, bench.text
    done = wait_for(client, f"{API}/benchmarks/runs/{bench.json()['id']}", terminal)
    assert done["summary"]["runs"] == 2 and done["summary"]["pass_rate"] == 1.0
    runs = client.get(f"{API}/runs", params={"benchmark_run_id": done["id"]}).json()
    assert runs["total"] == 2

    experiment = client.post(
        f"{API}/experiments",
        json={
            "name": "budget",
            "suite_id": "starter",
            "base_config": demo_config(),
            "task_ids": ["fix-failing-test"],
            "variants": [
                {"name": "baseline"},
                {"name": "tight", "overrides": {"limits": {"max_steps": 2}}},
            ],
        },
    )
    assert experiment.status_code == 202, experiment.text
    exp_id = experiment.json()["id"]
    result = wait_for(client, f"{API}/experiments/{exp_id}", lambda b: terminal(b["experiment"]))
    rows = {r["variant"]: r for r in result["comparison"]}
    assert rows["baseline"]["pass_rate"] == 1.0 and rows["tight"]["pass_rate"] == 0.0

    assert (
        client.post(
            f"{API}/benchmarks/runs", json={"suite_id": "missing", "config": demo_config()}
        ).status_code
        == 404
    )


def test_api_key_enforced(settings: Settings) -> None:
    settings.api_key = "test-api-key-123"
    with TestClient(create_app(settings)) as client:
        assert client.get(f"{API}/health").status_code == 200  # health stays public
        assert client.get(f"{API}/agents").status_code == 401
        assert (
            client.get(f"{API}/agents", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )
        ok = client.get(f"{API}/agents", headers={"Authorization": "Bearer test-api-key-123"})
        assert ok.status_code == 200


def test_prometheus_metrics(client: TestClient) -> None:
    run_id = client.post(
        f"{API}/runs", json={"goal": "Create hello.txt please", "config": demo_config()}
    ).json()["id"]
    wait_for(client, f"{API}/runs/{run_id}", terminal)
    response = client.get(f"{API}/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert 'agentforge_runs{status="succeeded"} 1' in body
    assert "# TYPE agentforge_run_duration_seconds summary" in body
    assert 'agentforge_run_duration_seconds_count{status="succeeded"} 1' in body
    assert 'agentforge_tool_calls{status="success",tool="write_file"} 1' in body
    assert "agentforge_runs_unknown_cost 0" in body


def test_cancel_orphaned_run_sets_finished_at(client: TestClient) -> None:
    """Regression: cancelling a run not held by this process left finished_at empty."""
    from agentforge.core.config import AgentConfig
    from agentforge.core.models import Run, RunStatus

    service = client.app.state.service  # type: ignore[attr-defined]
    run = Run(agent_name="x", config=AgentConfig.model_validate(demo_config()), goal="orphan")
    run.status = RunStatus.RUNNING
    client.portal.call(service.runs.save, run)  # type: ignore[union-attr]
    body = client.post(f"{API}/runs/{run.id}/cancel").json()
    assert body["status"] == "cancelled"
    assert body["finished_at"] is not None
