"""End-to-end tests through the HTTP API (offline, scripted provider)."""

from __future__ import annotations

import json
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

    series = client.get(f"{API}/stats/timeseries", params={"days": 7}).json()
    assert series["days"] == 7 and len(series["series"]) == 7
    today = series["series"][-1]
    assert today["runs"] == 1 and today["succeeded"] == 1 and today["passed"] == 1
    assert sum(day["runs"] for day in series["series"][:-1]) == 0
    assert client.get(f"{API}/stats/timeseries", params={"days": 91}).status_code == 422

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


def test_approval_gate_pauses_then_resumes_on_approve(client: TestClient) -> None:
    config = demo_config()
    config["approval"] = {"require_for": ["fs:write"], "timeout_seconds": 30}
    config["model"]["options"] = {
        "turns": [
            {
                "tool_calls": [
                    {"name": "write_file", "arguments": {"path": "out.txt", "content": "hi"}}
                ]
            },
            {"text": "done"},
        ]
    }
    run_id = client.post(f"{API}/runs", json={"goal": "write", "config": config}).json()["id"]
    wait_for(client, f"{API}/runs/{run_id}", lambda b: b["status"] == "awaiting_approval")

    pending = client.get(f"{API}/runs/{run_id}/approvals").json()
    assert len(pending) == 1
    assert pending[0]["tool"] == "write_file"
    assert pending[0]["permissions"] == ["fs:write"]

    decided = client.post(
        f"{API}/runs/{run_id}/approvals/{pending[0]['call_id']}", json={"approved": True}
    )
    assert decided.status_code == 200

    run = wait_for(client, f"{API}/runs/{run_id}", terminal)
    assert run["status"] == "succeeded"
    assert run["steps"][0]["tool_calls"][0]["status"] == "success"


def test_approval_gate_denies_and_run_continues(client: TestClient) -> None:
    config = demo_config()
    config["approval"] = {"require_for": ["fs:write"]}
    config["model"]["options"] = {
        "turns": [
            {
                "tool_calls": [
                    {"name": "write_file", "arguments": {"path": "out.txt", "content": "hi"}}
                ]
            },
            {"text": "done"},
        ]
    }
    run_id = client.post(f"{API}/runs", json={"goal": "write", "config": config}).json()["id"]
    wait_for(client, f"{API}/runs/{run_id}", lambda b: b["status"] == "awaiting_approval")
    call_id = client.get(f"{API}/runs/{run_id}/approvals").json()[0]["call_id"]

    client.post(
        f"{API}/runs/{run_id}/approvals/{call_id}", json={"approved": False, "reason": "not now"}
    )
    run = wait_for(client, f"{API}/runs/{run_id}", terminal)
    assert run["status"] == "succeeded"  # the run continues; only the tool call is denied
    call = run["steps"][0]["tool_calls"][0]
    assert call["status"] == "denied" and "not now" in call["error"]


def test_approval_endpoints_404_for_missing_run_or_call(client: TestClient) -> None:
    assert client.get(f"{API}/runs/run_missing/approvals").status_code == 404
    run_id = client.post(
        f"{API}/runs", json={"goal": "Create hello.txt", "config": demo_config()}
    ).json()["id"]
    wait_for(client, f"{API}/runs/{run_id}", terminal)
    resp = client.post(f"{API}/runs/{run_id}/approvals/call_x_y", json={"approved": True})
    assert resp.status_code == 404


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


def test_event_stream_carries_streamed_model_output(client: TestClient) -> None:
    """model.stream: token deltas reach SSE clients; the stored run has the whole text."""
    import json

    thought = "I will write the greeting file and then report back to the user in one line."
    config = demo_config()
    config["model"]["stream"] = True
    config["model"]["options"] = {
        "stream_delay_seconds": 0.05,  # keeps the run alive while the test subscribes
        "turns": [
            {
                "text": thought,
                "tool_calls": [
                    {"name": "write_file", "arguments": {"path": "hello.txt", "content": "hi\n"}}
                ],
            },
            {"text": "Done."},
        ],
    }
    run_id = client.post(f"{API}/runs", json={"goal": "Create hello.txt", "config": config}).json()[
        "id"
    ]
    with client.stream("GET", f"{API}/runs/{run_id}/events") as stream:
        body = "".join(stream.iter_text())

    events = [
        json.loads(block.split("data: ", 1)[1])
        for block in body.split("\n\n")
        if block.startswith("event: llm.delta")
    ]
    first_step = "".join(e["data"]["text"] for e in events if e["data"]["step"] == 0)
    # The subscription may begin after the first words; what arrives is in order.
    assert first_step and thought.endswith(first_step)
    assert "event: step.finished" in body

    run = wait_for(client, f"{API}/runs/{run_id}", terminal)
    assert run["status"] == "succeeded", run
    assert run["steps"][0]["thought"] == thought
    assert run["result"] == "Done."


# ------------------------------------------------------- YAML import (parse)
def test_parse_agent_yaml_then_create(client: TestClient) -> None:
    text = (EXAMPLES / "agents" / "scripted-demo.yaml").read_text()
    parsed = client.post(f"{API}/agents/parse", json={"content": text})
    assert parsed.status_code == 200, parsed.text
    config = parsed.json()
    assert config["name"] == "scripted-demo"
    assert config["limits"]["max_steps"] == 15
    # Parsing stores nothing ...
    assert client.get(f"{API}/agents").json() == []
    # ... and what it returns is accepted by the create endpoint unchanged.
    created = client.post(f"{API}/agents", json=config)
    assert created.status_code == 201, created.text
    assert created.json()["config"] == config


def test_parse_agent_accepts_json_text(client: TestClient) -> None:
    parsed = client.post(f"{API}/agents/parse", json={"content": json.dumps(demo_config())})
    assert parsed.status_code == 200, parsed.text
    assert parsed.json()["name"] == "scripted-demo"


@pytest.mark.parametrize(
    ("content", "fragment"),
    [
        ("name: [unclosed", "cannot parse agent config"),
        ("- just\n- a list\n", "expected a mapping"),
        ("just a sentence", "expected a mapping"),
        ("name: x\nmodel: {provider: scripted}\nno_such_field: 1\n", "no_such_field"),
        ("description: no name\n", "name"),
        # a "billion laughs" document: tiny text, exponentially large once walked
        (
            "a: &a [x, x, x, x, x, x, x, x, x]\n"
            + "".join(
                f"{c}: &{c} [*{p}, *{p}, *{p}, *{p}, *{p}, *{p}, *{p}, *{p}, *{p}]\n"
                for p, c in zip("abcdefgh", "bcdefghi", strict=True)
            )
            + "name: bomb\nmodel: {provider: scripted, options: {x: *i}}\n",
            "aliases",
        ),
        # python object tags must never be constructed
        ("name: !!python/object/apply:os.system ['true']\n", "cannot parse agent config"),
    ],
)
def test_parse_agent_rejects_bad_text(client: TestClient, content: str, fragment: str) -> None:
    response = client.post(f"{API}/agents/parse", json={"content": content})
    assert response.status_code == 400, response.text
    assert fragment in response.json()["detail"]


def test_parse_agent_requires_content(client: TestClient) -> None:
    assert client.post(f"{API}/agents/parse", json={"content": ""}).status_code == 422
    assert client.post(f"{API}/agents/parse", json={}).status_code == 422


def test_vector_memory_recall_through_the_api(settings: Settings) -> None:
    """A server with an embedder: an agent's vector recall embeds and caches its memories."""
    import asyncio

    from sqlalchemy import select

    from agentforge.storage.db import Database, MemoryEmbeddingRow, MemoryRow

    async def stored() -> tuple[list[str], list[tuple[str, str, int]]]:
        db = Database(settings.resolved_database_url)
        try:
            async with db.session() as session:
                memories = list((await session.scalars(select(MemoryRow.id))).all())
                rows = (await session.scalars(select(MemoryEmbeddingRow))).all()
                return memories, [(r.memory_id, r.embedder, r.dimensions) for r in rows]
        finally:
            await db.dispose()

    config = demo_config() | {
        "memory": {"persist": True, "search": "vector", "min_similarity": 0.15}
    }
    goal = "Create a file named hello.txt containing exactly the text: Hello, AgentForge!"
    with TestClient(
        create_app(settings.model_copy(update={"memory_embedder": "hashing"}))
    ) as client:
        created = client.post(f"{API}/agents", json=config)
        assert created.status_code == 201, created.text
        agent = created.json()
        assert agent["config"]["memory"]["search"] == "vector"
        for expected_vectors in (0, 1):
            # Run 1 has nothing to recall; run 2 recalls run 1's summary by vector search.
            run = client.post(f"{API}/runs", json={"agent_id": agent["id"], "goal": goal}).json()
            done = wait_for(client, f"{API}/runs/{run['id']}", terminal)
            assert done["status"] == "succeeded", done
            memories, vectors = asyncio.run(stored())
            assert len(memories) == expected_vectors + 1
            assert len(vectors) == expected_vectors
        ((memory_id, embedder, dimensions),) = vectors
        assert memory_id in memories and (embedder, dimensions) == ("hashing-v1:256", 256)

        rejected = client.post(
            f"{API}/agents", json=config | {"name": "bad", "memory": {"search": "semantic"}}
        )
        assert rejected.status_code == 422
