"""Improvement loop through the HTTP API (offline, scripted provider)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from agentforge.api.app import create_app
from agentforge.settings import Settings
from tests.e2e.test_api import API, terminal, wait_for

pytestmark = pytest.mark.e2e

DOGFOOD = Path(__file__).resolve().parents[2] / "dogfood"


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def demo_agent() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(
        (DOGFOOD / "agents" / "offline" / "demo-coder-v1.yaml").read_text()
    )
    return data


def start_benchmark(client: TestClient, agent_id: str, repeats: int = 1) -> dict[str, Any]:
    response = client.post(
        f"{API}/benchmarks/runs",
        json={"suite_id": "dogfood-coding", "agent_id": agent_id, "repeats": repeats},
    )
    assert response.status_code == 202, response.text
    bench = response.json()
    assert (bench["agent_id"], bench["agent_version"]) == (agent_id, 1)
    assert bench["result_class"] == "offline"
    done = wait_for(client, f"{API}/benchmarks/runs/{bench['id']}", terminal)
    assert done["status"] == "succeeded"
    return done


def test_dogfood_suites_are_served(client: TestClient) -> None:
    suites = {s["id"] for s in client.get(f"{API}/benchmarks/suites").json()}
    assert {
        "starter",
        "dogfood-coding",
        "dogfood-debugging",
        "dogfood-data",
        "dogfood-security",
        "dogfood-issues",
    } <= suites


def test_improvement_loop_via_api(client: TestClient) -> None:
    agent = client.post(f"{API}/agents", json=demo_agent()).json()
    versions = client.get(f"{API}/agents/{agent['id']}/versions").json()
    assert [(v["version"], v["source"]) for v in versions] == [(1, "created")]

    baseline = start_benchmark(client, agent["id"], repeats=2)
    analysis = client.get(f"{API}/benchmarks/runs/{baseline['id']}/analysis").json()
    assert analysis["categories"] == {"step_limit": 4}
    report = client.get(f"{API}/benchmarks/runs/{baseline['id']}/report").json()
    assert report["result_class"] == "offline" and report["summary"]["passed"] == 0
    assert report["runs"][0]["input_tokens"] is None
    assert report["runs"][0]["actual_cost_usd"] is None
    filtered = client.get(
        f"{API}/benchmarks/runs", params={"agent_id": agent["id"], "result_class": "real"}
    ).json()
    assert filtered == []

    categories = client.get(f"{API}/improvements/categories").json()
    assert "step_limit" in categories

    created = client.post(f"{API}/improvements", json={"benchmark_run_id": baseline["id"]})
    assert created.status_code == 201, created.text
    cycle = created.json()
    assert cycle["status"] == "proposed"
    assert cycle["proposal"]["changes"][0]["path"] == "limits.max_steps"

    applied = client.post(f"{API}/improvements/{cycle['id']}/apply", json={})
    assert applied.status_code == 200, applied.text
    assert applied.json()["to_version"] == 2
    assert client.post(f"{API}/improvements/{cycle['id']}/apply").status_code == 409

    started = client.post(f"{API}/improvements/{cycle['id']}/evaluate")
    assert started.status_code == 202, started.text
    assert started.json()["status"] == "evaluating"
    evaluated = wait_for(
        client, f"{API}/improvements/{cycle['id']}", lambda c: c["status"] != "evaluating"
    )
    assert evaluated["status"] == "evaluated", evaluated
    assert evaluated["comparison"]["verdict"] == "improved"
    assert evaluated["comparison"]["pass_rate_delta"] == 1.0

    compared = client.get(
        f"{API}/benchmarks/compare",
        params={"baseline": baseline["id"], "candidate": evaluated["candidate_benchmark_run_id"]},
    ).json()
    assert compared["verdict"] == "improved"

    # The CI regression gate agrees: improved = pass; the reverse direction regresses.
    candidate_id = evaluated["candidate_benchmark_run_id"]
    gate = client.get(
        f"{API}/benchmarks/gate", params={"baseline": baseline["id"], "candidate": candidate_id}
    ).json()
    assert (gate["verdict"], gate["exit_code"]) == ("pass", 0)
    reverse = client.get(
        f"{API}/benchmarks/gate", params={"baseline": candidate_id, "candidate": baseline["id"]}
    ).json()
    assert (reverse["verdict"], reverse["exit_code"]) == ("regression", 1)
    lenient = client.get(
        f"{API}/benchmarks/gate",
        params={
            "baseline": candidate_id,
            "candidate": baseline["id"],
            "max_pass_rate_drop": 1,
            "max_task_pass_rate_drop": 1,
            "max_mean_score_drop": 1,
        },
    ).json()
    assert lenient["verdict"] == "pass"
    assert (
        client.get(
            f"{API}/benchmarks/gate",
            params={"baseline": baseline["id"], "candidate": candidate_id, "min_pass_rate": 2},
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"{API}/benchmarks/gate",
            params={"baseline": "bench_missing", "candidate": candidate_id},
        ).status_code
        == 404
    )

    history = client.get(f"{API}/improvements", params={"agent_id": agent["id"]}).json()
    assert [c["id"] for c in history] == [cycle["id"]]
    versions = client.get(f"{API}/agents/{agent['id']}/versions").json()
    assert [(v["version"], v["source"]) for v in versions] == [
        (2, "improvement"),
        (1, "created"),
    ]
    v2 = client.get(f"{API}/agents/{agent['id']}/versions/2").json()
    assert v2["config"]["limits"]["max_steps"] == 20 and v2["improvement_id"] == cycle["id"]

    rejected = client.post(f"{API}/improvements/{cycle['id']}/reject", json={"reason": "test"})
    assert rejected.json()["reverted_to_version"] == 3
    assert client.get(f"{API}/agents/{agent['id']}").json()["version"] == 3


def test_improvement_api_rejects_unsafe_manual_changes(client: TestClient) -> None:
    agent = client.post(f"{API}/agents", json=demo_agent()).json()
    baseline = start_benchmark(client, agent["id"])
    response = client.post(
        f"{API}/improvements",
        json={
            "benchmark_run_id": baseline["id"],
            "changes": [{"path": "model.base_url", "value": "https://attacker.example"}],
        },
    )
    assert response.status_code == 409
    assert "cannot be changed" in response.json()["detail"]
    manual = client.post(
        f"{API}/improvements",
        json={
            "benchmark_run_id": baseline["id"],
            "changes": [{"path": "limits.max_steps", "value": 10, "rationale": "try"}],
        },
    ).json()
    assert manual["proposal"]["proposer"] == "manual"
    assert client.get(f"{API}/improvements/imp_missing").status_code == 404


def test_update_agent_records_change_summary(client: TestClient) -> None:
    agent = client.post(f"{API}/agents", json=demo_agent()).json()
    config = {**demo_agent(), "description": "edited"}
    updated = client.put(
        f"{API}/agents/{agent['id']}", params={"change_summary": "clarify"}, json=config
    ).json()
    assert updated["version"] == 2
    same = client.put(f"{API}/agents/{agent['id']}", json=config).json()
    assert same["version"] == 2
    latest = client.get(f"{API}/agents/{agent['id']}/versions").json()[0]
    assert (latest["version"], latest["change_summary"]) == (2, "clarify")


def test_benchmark_records_the_version_whose_config_it_ran(client: TestClient) -> None:
    """Regression: config and agent_version come from the same stored snapshot."""
    agent = client.post(f"{API}/agents", json=demo_agent()).json()
    config = {**demo_agent(), "description": "second", "limits": {"max_steps": 20}}
    assert client.put(f"{API}/agents/{agent['id']}", json=config).json()["version"] == 2
    response = client.post(
        f"{API}/benchmarks/runs",
        json={"suite_id": "dogfood-coding", "agent_id": agent["id"], "task_ids": ["add-cli-flag"]},
    )
    bench = response.json()
    assert bench["agent_version"] == 2
    assert bench["agent_config"]["limits"]["max_steps"] == 20
    wait_for(client, f"{API}/benchmarks/runs/{bench['id']}", terminal)
