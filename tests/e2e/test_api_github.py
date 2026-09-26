"""GitHub endpoints end-to-end: mocked GitHub API + local bare git remote."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from agentforge.api.app import create_app
from agentforge.settings import Settings
from tests.conftest import scripted_config
from tests.e2e.test_api import terminal, wait_for
from tests.integration.test_github_workflow import FIX_TURNS, FakeGitHub, git

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(shutil.which("git") is None, reason="git not installed"),
]

API = "/api/v1"


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    seed = tmp_path / "seed"
    seed.mkdir()
    git("init", "-q", "-b", "main", cwd=seed)
    (seed / "greet.py").write_text("def greet(name):\n    return 'Helo ' + name\n")
    git("add", "-A", cwd=seed)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=seed)
    bare = tmp_path / "remote.git"
    git("clone", "-q", "--bare", str(seed), str(bare), cwd=tmp_path)
    return bare


@pytest.fixture
def client(
    settings: Settings, bare_remote: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, FakeGitHub]]:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_" + "y" * 36)
    fake = FakeGitHub()
    app = create_app(settings)
    with TestClient(app) as test_client:
        service = app.state.service
        service.github_transport = httpx.MockTransport(fake)
        service.github_remote_for = lambda repo: str(bare_remote)
        yield test_client, fake


def test_github_endpoints_and_task(
    client: tuple[TestClient, FakeGitHub], bare_remote: Path
) -> None:
    http, fake = client
    assert http.get(f"{API}/github/status").json()["token_configured"] is True
    repo = http.get(f"{API}/github/repos/acme/app").json()
    assert repo["default_branch"] == "main"

    config = scripted_config(FIX_TURNS, tools=["filesystem", "git"]).model_dump(mode="json")
    created = http.post(
        f"{API}/github/tasks",
        json={
            "repo": "acme/app",
            "issue_number": 12,
            "config": config,
            "push": True,
            "open_pr": True,
        },
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["id"]
    run = wait_for(http, f"{API}/runs/{run_id}", lambda b: terminal(b) and "commits" in b["labels"])
    assert run["status"] == "succeeded", run["error"]
    assert run["labels"]["pr_url"] == "https://github.com/acme/app/pull/13"
    assert run["labels"]["pushed"] == "true"
    assert "Fix greeting typo" in run["goal"]
    assert "Fix greeting typo (#12)" in git(
        "log", "--oneline", run["labels"]["branch"], cwd=bare_remote
    )

    tasks = http.get(f"{API}/github/tasks").json()
    assert tasks["total"] == 1 and tasks["items"][0]["id"] == run_id
    assert not any("merge" in r.url.path for r in fake.requests)


def test_github_task_validation(client: tuple[TestClient, FakeGitHub]) -> None:
    http, _ = client
    config = scripted_config([]).model_dump(mode="json")
    bad_repo = http.post(
        f"{API}/github/tasks", json={"repo": "not a repo", "issue_number": 1, "config": config}
    )
    assert bad_repo.status_code == 422
    pr_without_push = http.post(
        f"{API}/github/tasks",
        json={"repo": "a/b", "issue_number": 1, "config": config, "open_pr": True},
    )
    assert pr_without_push.status_code == 422
    missing_issue = http.post(
        f"{API}/github/tasks", json={"repo": "acme/app", "issue_number": 99, "config": config}
    )
    run_id = missing_issue.json()["id"]
    run = wait_for(http, f"{API}/runs/{run_id}", terminal)
    assert run["status"] == "failed" and run["error"]["type"] == "github"
    assert http.get(f"{API}/github/repos/acme/missing").status_code == 404
