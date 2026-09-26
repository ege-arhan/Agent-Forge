from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest

from agentforge.core.models import RunStatus
from agentforge.integrations.github.client import GitHubClient
from agentforge.integrations.github.workflow import (
    GitHubWorkflowError,
    IssueTaskRequest,
    branch_name,
    solve_issue,
)
from agentforge.settings import Settings
from tests.conftest import scripted_config

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("git") is None, reason="git not installed"),
]

TOKEN = "ghp_" + "x" * 36


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    seed = tmp_path / "seed"
    seed.mkdir()
    git("init", "-q", "-b", "main", cwd=seed)
    (seed / "greet.py").write_text("def greet(name):\n    return 'Helo ' + name\n")
    git("add", "-A", cwd=seed)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=seed)
    bare = tmp_path / "remote.git"
    git("clone", "-q", "--bare", str(seed), str(bare), cwd=tmp_path)
    return bare


class FakeGitHub:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/comments"):
            return httpx.Response(
                200, json=[{"user": {"login": "rev"}, "body": "typo in greeting"}]
            )
        if path.endswith("/issues/12"):
            return httpx.Response(
                200,
                json={
                    "number": 12,
                    "title": "Fix greeting typo",
                    "body": "greet() says Helo",
                    "state": "open",
                    "html_url": "https://github.com/acme/app/issues/12",
                    "labels": [],
                },
            )
        if path.endswith("/pulls") and request.method == "POST":
            body = json.loads(request.content)
            return httpx.Response(
                201,
                json={
                    "number": 13,
                    "title": body["title"],
                    "html_url": "https://github.com/acme/app/pull/13",
                    "state": "open",
                    "draft": body["draft"],
                    "head": {"ref": body["head"]},
                    "base": {"ref": body["base"]},
                },
            )
        if path == "/repos/acme/app":
            return httpx.Response(200, json={"full_name": "acme/app", "default_branch": "main"})
        return httpx.Response(404, json={"message": "not found"})


FIX_TURNS: list[dict[str, Any]] = [
    {
        "tool_calls": [
            {
                "name": "edit_file",
                "arguments": {"path": "greet.py", "old_text": "'Helo '", "new_text": "'Hello '"},
            }
        ]
    },
    {"tool_calls": [{"name": "git_commit", "arguments": {"message": "Fix greeting typo (#12)"}}]},
    {"text": "Fixed the typo in greet()."},
]


async def test_issue_to_draft_pr(settings: Settings, remote: Path) -> None:
    fake = FakeGitHub()
    config = scripted_config(FIX_TURNS, tools=["filesystem", "git"])
    async with GitHubClient(TOKEN, transport=httpx.MockTransport(fake)) as client:
        result = await solve_issue(
            IssueTaskRequest(
                repo="acme/app",
                issue_number=12,
                config=config,
                push=True,
                open_pr=True,
                test_command="python3 -c \"import greet; assert greet.greet('a') == 'Hello a'\"",
                remote_url=str(remote),
            ),
            settings=settings,
            client=client,
            token=TOKEN,
            env={},
        )
    assert result.run.status == RunStatus.SUCCEEDED
    assert result.run.evaluation is not None and result.run.evaluation.passed
    assert result.branch == "agentforge/issue-12-fix-greeting-typo"
    assert result.commits == 1 and result.pushed
    assert result.pr_url == "https://github.com/acme/app/pull/13"
    assert "typo in greeting" in result.run.goal  # issue discussion included
    assert result.run.labels["github_issue"] == "12"

    pushed = git("log", "--oneline", result.branch, cwd=remote)
    assert "Fix greeting typo (#12)" in pushed
    assert "main" in git("branch", cwd=remote)  # base untouched
    pr_request = next(r for r in fake.requests if r.url.path.endswith("/pulls"))
    body = json.loads(pr_request.content)
    assert body["draft"] is True and body["base"] == "main"
    assert "never merges" in body["body"] and "Closes #12" in body["body"]
    assert not any("merge" in r.url.path for r in fake.requests)
    # The token never reaches the agent or the run record.
    assert TOKEN not in result.run.model_dump_json()


async def test_failed_evaluation_blocks_push(settings: Settings, remote: Path) -> None:
    config = scripted_config([{"text": "I did nothing."}], tools=["filesystem", "git"])
    async with GitHubClient(TOKEN, transport=httpx.MockTransport(FakeGitHub())) as client:
        result = await solve_issue(
            IssueTaskRequest(
                repo="acme/app",
                issue_number=12,
                config=config,
                push=True,
                open_pr=True,
                remote_url=str(remote),
            ),
            settings=settings,
            client=client,
            token=TOKEN,
            env={},
        )
    assert not result.pushed and result.pr_url is None
    assert result.commits == 0
    assert any("no commits" in n for n in result.notes)


async def test_uncommitted_changes_are_committed_but_not_pushed(
    settings: Settings, remote: Path
) -> None:
    config = scripted_config([*FIX_TURNS[:1], {"text": "done"}], tools=["filesystem"])
    async with GitHubClient(TOKEN, transport=httpx.MockTransport(FakeGitHub())) as client:
        result = await solve_issue(
            IssueTaskRequest(
                repo="acme/app", issue_number=12, config=config, remote_url=str(remote)
            ),
            settings=settings,
            client=client,
            token=TOKEN,
            env={},
        )
    assert result.commits == 1 and not result.pushed
    assert any("uncommitted" in n for n in result.notes)


async def test_open_pr_requires_push(settings: Settings) -> None:
    async with GitHubClient(TOKEN, transport=httpx.MockTransport(FakeGitHub())) as client:
        with pytest.raises(GitHubWorkflowError):
            await solve_issue(
                IssueTaskRequest(
                    repo="acme/app", issue_number=12, config=scripted_config([]), open_pr=True
                ),
                settings=settings,
                client=client,
                token=TOKEN,
                env={},
            )


def test_branch_name_slug() -> None:
    from agentforge.integrations.github.client import Issue

    issue = Issue(number=5, title="Crash on  ÜNICODE input!!", state="open", html_url="")
    assert branch_name(issue) == "agentforge/issue-5-crash-on-nicode-input"
