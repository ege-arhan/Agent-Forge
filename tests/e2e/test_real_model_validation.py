"""The limited real-model validation harness, against a local fake OpenCode Go server.

No real model is called. The fake server behaves like OpenCode Go where it
matters: ``/models`` is public (so it proves nothing about authentication),
model requests without ``x-opencode-session`` get ``400 MissingSessionID``, and
Muse Spark is served on ``/responses``. The whole path (preflight, opencode-go
preset through the OpenAI SDK, both authentication modes, tool calling,
evaluation, gating, execution cap, reports, secret scans) is exercised.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import socket
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
FAKE_KEY = "oc-test-key-5f2c9d71e8a64b03"
ALL_MODELS = [
    "deepseek-v4.1-flash",
    "mimo-v2.6-flash",
    "muse-spark-1.3-contributor",
    "glm-5.3-flash",
    "kimi-k2.7-code",
]


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


def _response(model: str, output: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "resp",
        "object": "response",
        "created_at": 0,
        "model": model,
        "status": "completed",
        "output": output,
        "usage": {"input_tokens": 50, "output_tokens": 10, "total_tokens": 60},
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }


GREETING_ARGS = json.dumps({"path": "hello.txt", "content": "Hello, AgentForge!\n"})


def fake_app(
    listed: list[str],
    good_models: set[str],
    calls: list[dict[str, Any]],
    *,
    auth: str,
    reject_auth: bool = False,
) -> FastAPI:
    """``auth="env"`` expects the bearer key; ``auth="proxy"`` expects no header at all
    (the real egress proxy adds it after the request leaves the process)."""
    app = FastAPI()
    expected_auth = f"Bearer {FAKE_KEY}" if auth == "env" else None

    @app.get("/v1/models")
    async def models() -> Any:  # public, like OpenCode Go's listing
        return {"object": "list", "data": [{"id": m, "object": "model"} for m in listed]}

    def gate(request: Request, model: str, api: str) -> JSONResponse | None:
        session = request.headers.get("x-opencode-session")
        calls.append(
            {
                "model": model,
                "api": api,
                "session": session,
                "authorization": request.headers.get("authorization"),
                "user_agent": request.headers.get("user-agent"),
            }
        )
        if not session:
            return JSONResponse({"error": {"type": "MissingSessionID"}}, status_code=400)
        if reject_auth or request.headers.get("authorization") != expected_auth:
            return JSONResponse({"error": {"type": "AuthError"}}, status_code=401)
        return None

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Any:
        body = await request.json()
        model = body["model"]
        if (rejected := gate(request, model, "chat")) is not None:
            return rejected
        assert "max_tokens" in body
        assistant_turns = sum(1 for m in body["messages"] if m["role"] == "assistant")
        goal = next(m["content"] for m in body["messages"] if m["role"] == "user")
        if model in good_models and "hello.txt" in goal and assistant_turns == 0:
            call = {
                "id": "c1",
                "type": "function",
                "function": {"name": "write_file", "arguments": GREETING_ARGS},
            }
            return _completion(
                model, {"role": "assistant", "content": None, "tool_calls": [call]}, "tool_calls"
            )
        return _completion(model, {"role": "assistant", "content": "Done."}, "stop")

    @app.post("/v1/responses")
    async def responses(request: Request) -> Any:
        body = await request.json()
        model = body["model"]
        if (rejected := gate(request, model, "responses")) is not None:
            return rejected
        assert "max_output_tokens" in body
        items = body["input"]
        goal = next(i["content"] for i in items if i.get("role") == "user")
        called = any(i.get("type") == "function_call" for i in items)
        if model in good_models and "hello.txt" in goal and not called:
            call = {
                "type": "function_call",
                "id": "fc1",
                "call_id": "c1",
                "name": "write_file",
                "arguments": GREETING_ARGS,
                "status": "completed",
            }
            return _response(model, [call])
        text = {"type": "output_text", "text": "Done.", "annotations": []}
        message = {
            "type": "message",
            "id": "m1",
            "role": "assistant",
            "status": "completed",
            "content": [text],
        }
        return _response(model, [message])

    return app


@contextmanager
def serve(app: FastAPI) -> Iterator[str]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}/v1"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def run_main(module: ModuleType, base_url: str, tmp_path: Path, *extra: str) -> int:
    code: int = module.main(
        [
            "--base-url",
            base_url,
            "--results",
            str(tmp_path / "results"),
            "--data-dir",
            str(tmp_path / "data"),
            "--sandbox",
            "local",
            *extra,
        ]
    )
    return code


def load_summary(tmp_path: Path) -> dict[str, Any]:
    [path] = (tmp_path / "results" / "real").glob("limited-validation-*/summary.json")
    summary: dict[str, Any] = json.loads(path.read_text())
    return summary


def assert_key_nowhere(tmp_path: Path, *texts: str) -> None:
    for text in texts:
        assert FAKE_KEY not in text
        assert "Bearer" not in text  # no Authorization header is ever logged or printed
    for path in tmp_path.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert FAKE_KEY.encode() not in data, path
            assert b"Bearer " not in data, path


# ------------------------------------------------------------------ unit level
def test_secret_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_script(monkeypatch)
    (tmp_path / "a.json").write_text('{"x": 1}')
    assert module.secret_found([tmp_path], FAKE_KEY) is False
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.log").write_text(f"token={FAKE_KEY}")
    assert module.secret_found([tmp_path], FAKE_KEY) is True


def test_credential_pattern_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The scan that works in proxy mode, where the key itself is never known.
    module = load_script(monkeypatch)
    (tmp_path / "run.json").write_text('{"session": "run_0123456789abcdef", "model": "glm"}')
    assert module.credential_pattern_found([tmp_path]) is False
    (tmp_path / "trace.log").write_text("Authorization: Bearer abcdefghijklmnop0123456789")
    assert module.credential_pattern_found([tmp_path]) is True
    assert module.credential_pattern_found([tmp_path / "missing"]) is False


def test_models_are_exact_listed_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_script(monkeypatch)
    assert [model_id for _, model_id in module.MODELS] == ALL_MODELS
    assert module.BASE_URL == "https://opencode.ai/zen/go/v1"
    assert module.resolve_model_id("glm-5.3-flash", {"glm-5.3-flash"}) == "glm-5.3-flash"
    assert module.resolve_model_id("opencode-go/glm-5.3-flash", {"glm-5.3-flash"}) is None
    assert module.resolve_model_id("x", {"y"}) is None


async def test_preflight_reports_http_errors_without_model_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_script(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")  # never a completion
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(module.PreflightError) as info:
        await module.preflight("https://go.test/v1", "k", transport=httpx.MockTransport(handler))
    assert info.value.kind == "configuration failure"


@pytest.mark.parametrize("key", [FAKE_KEY, None])
async def test_preflight_sends_a_key_only_in_env_mode(
    monkeypatch: pytest.MonkeyPatch, key: str | None
) -> None:
    module = load_script(monkeypatch)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "glm-5.3-flash"}]})

    available = await module.preflight(
        "https://go.test/v1", key, transport=httpx.MockTransport(handler)
    )
    assert available == {"glm-5.3-flash"}
    expected = f"Bearer {FAKE_KEY}" if key else None
    assert seen[0].headers.get("authorization") == expected


def test_env_mode_needs_the_key_and_proxy_mode_needs_the_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load_script(monkeypatch)
    for name in ("OPENCODE_API_KEY", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    # Unroutable endpoint: reaching it at all would fail the test.
    assert run_main(module, "http://127.0.0.1:9/v1", tmp_path) == 2
    assert "--auth proxy" in capsys.readouterr().out
    assert run_main(module, "http://127.0.0.1:9/v1", tmp_path, "--auth", "proxy") == 2
    assert "HTTPS_PROXY" in capsys.readouterr().out
    assert not (tmp_path / "results").exists()


# -------------------------------------------------------------------- end to end
def test_limited_validation_end_to_end_env_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[dict[str, Any]] = []
    good = {"deepseek-v4.1-flash", "glm-5.3-flash", "muse-spark-1.3-contributor"}
    module = load_script(monkeypatch)
    monkeypatch.setenv("OPENCODE_API_KEY", FAKE_KEY)
    caplog.set_level(logging.DEBUG)  # SDK/HTTP debug logs must not carry the key either
    with serve(fake_app(ALL_MODELS, good, calls, auth="env")) as base_url:
        code = run_main(module, base_url, tmp_path)
    out = capsys.readouterr().out
    assert code == 0, out
    assert "secret scan: clean" in out
    assert "not verified by the listing" in out
    summary = load_summary(tmp_path)
    rows = {(r["model_id"], r["phase"]): r for r in summary["rows"]}
    assert summary["provider"] == "OpenCode Go" and summary["result_class"] == "real"
    assert summary["secret_scan"] == "clean"
    assert summary["auth_mode"].startswith("env")
    assert summary["authentication"] == "verified by a successful model call"

    # Smoke passed -> both benchmark tasks ran (and failed: the fake answers "Done.").
    for model in good:
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
    assert summary["executions"] == 11 <= summary["max_executions"] == 15

    # Every model request carried a session id: its run's id - one per run,
    # stable across that run's calls, different between runs.
    assert calls and all(c["session"] for c in calls)
    run_ids = {r["run_id"] for r in summary["rows"] if r["executed"]}
    assert {c["session"] for c in calls} == run_ids and len(run_ids) == 11
    smoke_run = rows[("glm-5.3-flash", "smoke")]["run_id"]
    assert sum(1 for c in calls if c["session"] == smoke_run) == 2
    assert all(c["user_agent"].startswith("agentforge/") for c in calls)
    # Muse Spark went through the Responses API, everything else Chat Completions.
    assert {c["api"] for c in calls if c["model"] == "muse-spark-1.3-contributor"} == {"responses"}
    assert {c["api"] for c in calls if c["model"] != "muse-spark-1.3-contributor"} == {"chat"}

    # Reports are stored as REAL results only; nothing under offline/.
    results = tmp_path / "results"
    reports = list((results / "real").glob("dogfood-*-v1/*.json"))
    reports += list((results / "real").glob("starter-v1/*.json"))
    assert len(reports) == 11
    assert all(json.loads(p.read_text())["provider"] == "opencode-go" for p in reports)
    assert not (results / "offline").exists()
    markdown = next((results / "real").glob("limited-validation-*/summary.md")).read_text()
    assert "REAL MODEL · GLM-5.3 Flash" in markdown and "not available" in markdown
    assert "Authentication: env" in markdown
    assert "HTTP Request: POST" in caplog.text  # the log capture is live, not vacuous
    assert_key_nowhere(tmp_path, out, caplog.text)


def test_limited_validation_proxy_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[dict[str, Any]] = []
    module = load_script(monkeypatch)
    monkeypatch.setattr(module, "MODELS", [("DeepSeek V4.1 Flash", "deepseek-v4.1-flash")])
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)  # the key is never in this process
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")  # only https:// URLs use it
    caplog.set_level(logging.DEBUG)
    with serve(fake_app(ALL_MODELS, {"deepseek-v4.1-flash"}, calls, auth="proxy")) as base_url:
        code = run_main(module, base_url, tmp_path, "--auth", "proxy")
    out = capsys.readouterr().out
    assert code == 0, out
    summary = load_summary(tmp_path)
    assert summary["auth_mode"].startswith("proxy")
    assert summary["authentication"] == "verified by a successful model call"
    assert summary["secret_scan"] == "clean"
    assert summary["executions"] == 3
    # No Authorization header left the process; sessions still sent per run.
    assert calls and all(c["authorization"] is None for c in calls)
    assert {c["session"] for c in calls} == {r["run_id"] for r in summary["rows"]}
    assert_key_nowhere(tmp_path, out, caplog.text)


def test_authentication_failure_stops_before_any_further_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The public listing succeeds, so it must not count as authentication:
    # the first model call is rejected and nothing else is called.
    calls: list[dict[str, Any]] = []
    module = load_script(monkeypatch)
    monkeypatch.setattr(
        module,
        "MODELS",
        [("DeepSeek V4.1 Flash", "deepseek-v4.1-flash"), ("GLM-5.3 Flash", "glm-5.3-flash")],
    )
    monkeypatch.setenv("OPENCODE_API_KEY", FAKE_KEY)
    app = fake_app(ALL_MODELS, set(ALL_MODELS), calls, auth="env", reject_auth=True)
    with serve(app) as base_url:
        code = run_main(module, base_url, tmp_path)
    out = capsys.readouterr().out
    assert code == 3, out
    assert "authentication failed" in out
    assert len(calls) == 1  # one model call, no retry, no second model
    summary = load_summary(tmp_path)
    assert summary["authentication"].startswith("FAILED")
    assert summary["executions"] == 1
    first, *rest = summary["rows"]
    assert first["auth_failed"] is True
    assert first["failure_category"] == "configuration failure (authentication)"
    assert all(not r["executed"] for r in rest)
    assert any("rejected (HTTP 401/403)" in (r["failure_reason"] or "") for r in rest)
    assert_key_nowhere(tmp_path, out)


def test_execution_cap_is_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from agentforge.settings import Settings
    from agentforge.storage import Database

    calls: list[dict[str, Any]] = []
    module = load_script(monkeypatch)
    monkeypatch.setenv("OPENCODE_API_KEY", FAKE_KEY)
    settings = Settings(data_dir=tmp_path / "d", _env_file=None)  # type: ignore[call-arg]
    good = {"deepseek-v4.1-flash", "glm-5.3-flash"}

    async def run(base_url: str) -> list[Any]:
        db = Database(settings.resolved_database_url)
        await db.migrate()
        try:
            rows: list[Any] = await module.run_experiment(
                db=db,
                settings=settings,
                base_url=base_url,
                available=good,  # the other three are "not listed"
                token_budget=10_000,
                sandbox="local",
                max_executions=4,
            )
            return rows
        finally:
            await db.dispose()

    with serve(fake_app(ALL_MODELS, good, calls, auth="env")) as base_url:
        rows = asyncio.run(run(base_url))
    assert sum(1 for r in rows if r.executed) == 4
    assert any("execution cap (4) reached" in (r.failure_reason or "") for r in rows)
    unlisted = [r for r in rows if r.model_id not in good]
    assert unlisted and all(r.failure_category == "configuration failure" for r in unlisted)
    assert all(c["model"] in good for c in calls)
