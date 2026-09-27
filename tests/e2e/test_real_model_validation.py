"""The limited real-model validation harness, against a local fake OpenAI-compatible server.

No real model is called: the fake server lists models and replays tool calls,
so the whole path (preflight, opencode-go preset through the OpenAI SDK, tool
calling, evaluation, gating, execution cap, reports, secret scan) is exercised.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
FAKE_KEY = "oc-test-key-5f2c9d71e8a64b03"


def load_script(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "real_model_validation", ROOT / "scripts" / "real_model_validation.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _completion(model: str, message: dict[str, Any], finish: str) -> dict[str, Any]:
    return {
        "id": "cmpl",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "finish_reason": finish, "message": message}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
    }


def fake_app(listed: list[str], good_models: set[str], calls: list[str]) -> FastAPI:
    app = FastAPI()

    @app.get("/v1/models")
    async def models(request: Request) -> Any:
        if request.headers.get("authorization") != f"Bearer {FAKE_KEY}":
            return {"error": "unauthorized"}
        return {"object": "list", "data": [{"id": m, "object": "model"} for m in listed]}

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Any:
        body = await request.json()
        model = body["model"]
        calls.append(model)
        assert request.headers.get("authorization") == f"Bearer {FAKE_KEY}"
        assert "max_tokens" in body
        assistant_turns = sum(1 for m in body["messages"] if m["role"] == "assistant")
        goal = next(m["content"] for m in body["messages"] if m["role"] == "user")
        if model in good_models and "hello.txt" in goal and assistant_turns == 0:
            args = {"path": "hello.txt", "content": "Hello, AgentForge!\n"}
            return _completion(
                model,
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "write_file", "arguments": json.dumps(args)},
                        }
                    ],
                },
                "tool_calls",
            )
        return _completion(model, {"role": "assistant", "content": "Done."}, "stop")

    return app


@pytest.fixture
def fake_server() -> Iterator[tuple[str, list[str]]]:
    calls: list[str] = []
    # Listed: four models (short ids); muse-spark is missing -> configuration failure.
    listed = [
        "deepseek-v4.1-flash",
        "mimo-v2.6-flash",
        "glm-5.3-flash",
        "kimi-k2.7-code",
    ]
    good = {"deepseek-v4.1-flash", "glm-5.3-flash"}  # these pass the smoke task
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(fake_app(listed, good, calls), port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}/v1", calls
    server.should_exit = True
    thread.join(timeout=5)


def test_resolve_model_id() -> None:
    spec = importlib.util.spec_from_file_location(
        "rmv_resolve", ROOT / "scripts" / "real_model_validation.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        assert module.resolve_model_id("opencode-go/glm-5.3-flash", {"glm-5.3-flash"}) == (
            "glm-5.3-flash"
        )
        assert module.resolve_model_id("opencode-go/x", {"opencode-go/x"}) == "opencode-go/x"
        assert module.resolve_model_id("opencode-go/x", {"y"}) is None
    finally:
        del sys.modules[spec.name]


async def test_preflight_reports_auth_failure_without_model_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_script(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")  # never a completion
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(module.PreflightError) as info:
        await module.preflight(["https://go.test/v1"], "k", transport=httpx.MockTransport(handler))
    assert info.value.kind == "configuration failure"


def test_limited_validation_end_to_end(
    fake_server: tuple[str, list[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base_url, calls = fake_server
    module = load_script(monkeypatch)
    monkeypatch.setenv("OPENCODE_API_KEY", FAKE_KEY)
    results = tmp_path / "results"
    code = module.main(
        [
            "--base-url",
            base_url,
            "--results",
            str(results),
            "--data-dir",
            str(tmp_path / "data"),
            "--sandbox",
            "local",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert FAKE_KEY not in out
    [summary_path] = (results / "real").glob("limited-validation-*/summary.json")
    summary = json.loads(summary_path.read_text())
    rows = {(r["model_id"].split("/")[1], r["phase"]): r for r in summary["rows"]}
    assert summary["provider"] == "OpenCode Go" and summary["result_class"] == "real"
    assert summary["secret_scan"] == "clean"

    # Smoke passed -> both benchmark tasks ran (and failed: the fake answers "Done.").
    for model in ("deepseek-v4.1-flash", "glm-5.3-flash"):
        assert rows[(model, "smoke")]["task_success"] is True
        assert rows[(model, "smoke")]["input_tokens"] == 100  # two calls x 50
        assert rows[(model, "smoke")]["tool_usage"] == {"write_file": {"success": 1}}
        for phase in ("task-a", "task-b"):
            assert rows[(model, phase)]["executed"] is True
            assert rows[(model, phase)]["task_success"] is False
            assert rows[(model, phase)]["test_success"] is False
            assert rows[(model, phase)]["failure_category"] == "test failure"
            assert rows[(model, phase)]["actual_cost_usd"] is None
    # Smoke failed -> no benchmark tasks for that model.
    for model in ("mimo-v2.6-flash", "kimi-k2.7-code"):
        assert rows[(model, "smoke")]["task_success"] is False
        assert rows[(model, "task-a")]["executed"] is False
        assert "smoke task did not pass" in rows[(model, "task-a")]["failure_reason"]
    # Not listed by the endpoint -> configuration failure, no model call.
    muse = rows[("muse-spark-1.3-contributor", "smoke")]
    assert muse["executed"] is False and muse["failure_category"] == "configuration failure"
    assert "muse-spark-1.3-contributor" not in calls

    assert summary["executions"] == 8 <= summary["max_executions"] == 15
    # Reports are stored as REAL results only; nothing under offline/.
    reports = list((results / "real").glob("dogfood-*-v1/*.json"))
    reports += list((results / "real").glob("starter-v1/*.json"))
    assert len(reports) == 8
    assert all(json.loads(p.read_text())["provider"] == "opencode-go" for p in reports)
    assert not (results / "offline").exists()
    markdown = (summary_path.parent / "summary.md").read_text()
    assert "REAL MODEL · GLM-5.3 Flash" in markdown and "not available" in markdown
    # The key appears nowhere on disk (database, reports, log).
    for path in [*results.rglob("*"), *(tmp_path / "data").rglob("*")]:
        if path.is_file():
            assert FAKE_KEY.encode() not in path.read_bytes(), path


def test_execution_cap_is_enforced(
    fake_server: tuple[str, list[str]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from agentforge.settings import Settings
    from agentforge.storage import Database

    base_url, _ = fake_server
    module = load_script(monkeypatch)
    monkeypatch.setenv("OPENCODE_API_KEY", FAKE_KEY)
    settings = Settings(data_dir=tmp_path / "d", _env_file=None)  # type: ignore[call-arg]

    async def run() -> list[Any]:
        db = Database(settings.resolved_database_url)
        await db.migrate()
        try:
            rows: list[Any] = await module.run_experiment(
                db=db,
                settings=settings,
                base_url=base_url,
                available={"deepseek-v4.1-flash", "glm-5.3-flash"},
                token_budget=10_000,
                sandbox="local",
                max_executions=4,
            )
            return rows
        finally:
            await db.dispose()

    rows = asyncio.run(run())
    assert sum(1 for r in rows if r.executed) == 4
    assert any("execution cap (4) reached" in (r.failure_reason or "") for r in rows)
