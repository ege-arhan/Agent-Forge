"""Minimal async GitHub REST client.

Only the operations AgentForge needs are implemented. There is deliberately
no merge operation: pull requests opened by agents always require a human
review and merge.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from pydantic import BaseModel

from agentforge.core.errors import AgentForgeError

API_URL = "https://api.github.com"
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubError(AgentForgeError):
    code = "github_error"

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def parse_repo(full_name: str) -> tuple[str, str]:
    if not _REPO_RE.match(full_name):
        raise GitHubError(f"invalid repository name '{full_name}', expected owner/name")
    owner, name = full_name.split("/", 1)
    return owner, name


class Issue(BaseModel):
    number: int
    title: str
    body: str | None = None
    state: str
    html_url: str
    labels: list[str] = []
    user: str | None = None
    is_pull_request: bool = False


class PullRequest(BaseModel):
    number: int
    title: str
    html_url: str
    state: str
    draft: bool = False
    head: str
    base: str


class GitHubClient:
    def __init__(
        self,
        token: str | None,
        *,
        base_url: str = API_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agentforge",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(
            base_url=base_url, headers=headers, transport=transport, timeout=timeout
        )

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise GitHubError(f"GitHub request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", "")
            except ValueError:
                detail = response.text[:200]
            raise GitHubError(
                f"GitHub API {method} {path} -> {response.status_code}: {detail}",
                status_code=response.status_code,
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def get_repository(self, repo: str) -> dict[str, Any]:
        owner, name = parse_repo(repo)
        data = await self._request("GET", f"/repos/{owner}/{name}")
        return {
            k: data.get(k)
            for k in (
                "full_name",
                "description",
                "default_branch",
                "private",
                "html_url",
                "language",
                "open_issues_count",
                "stargazers_count",
                "clone_url",
            )
        }

    async def list_issues(
        self, repo: str, *, state: str = "open", labels: list[str] | None = None, limit: int = 30
    ) -> list[Issue]:
        owner, name = parse_repo(repo)
        params: dict[str, Any] = {"state": state, "per_page": min(limit, 100)}
        if labels:
            params["labels"] = ",".join(labels)
        data = await self._request("GET", f"/repos/{owner}/{name}/issues", params=params)
        issues = [_issue(item) for item in data]
        return [i for i in issues if not i.is_pull_request][:limit]

    async def get_issue(self, repo: str, number: int) -> Issue:
        owner, name = parse_repo(repo)
        return _issue(await self._request("GET", f"/repos/{owner}/{name}/issues/{number}"))

    async def list_issue_comments(self, repo: str, number: int, limit: int = 50) -> list[str]:
        owner, name = parse_repo(repo)
        data = await self._request(
            "GET",
            f"/repos/{owner}/{name}/issues/{number}/comments",
            params={"per_page": min(limit, 100)},
        )
        return [f"{c.get('user', {}).get('login', '?')}: {c.get('body', '')}" for c in data]

    async def create_issue_comment(self, repo: str, number: int, body: str) -> str:
        owner, name = parse_repo(repo)
        data = await self._request(
            "POST", f"/repos/{owner}/{name}/issues/{number}/comments", json={"body": body}
        )
        return str(data.get("html_url", ""))

    async def get_branch_sha(self, repo: str, branch: str) -> str:
        owner, name = parse_repo(repo)
        data = await self._request("GET", f"/repos/{owner}/{name}/git/ref/heads/{branch}")
        return str(data["object"]["sha"])

    async def create_branch(self, repo: str, branch: str, from_sha: str) -> None:
        owner, name = parse_repo(repo)
        await self._request(
            "POST",
            f"/repos/{owner}/{name}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": from_sha},
        )

    async def create_pull_request(
        self, repo: str, *, title: str, head: str, base: str, body: str = "", draft: bool = True
    ) -> PullRequest:
        owner, name = parse_repo(repo)
        data = await self._request(
            "POST",
            f"/repos/{owner}/{name}/pulls",
            json={"title": title, "head": head, "base": base, "body": body, "draft": draft},
        )
        return _pull(data)

    async def list_pull_requests(
        self, repo: str, *, state: str = "open", limit: int = 30
    ) -> list[PullRequest]:
        owner, name = parse_repo(repo)
        data = await self._request(
            "GET",
            f"/repos/{owner}/{name}/pulls",
            params={"state": state, "per_page": min(limit, 100)},
        )
        return [_pull(item) for item in data][:limit]


def _issue(data: dict[str, Any]) -> Issue:
    return Issue(
        number=data["number"],
        title=data.get("title", ""),
        body=data.get("body"),
        state=data.get("state", ""),
        html_url=data.get("html_url", ""),
        labels=[
            lbl["name"] if isinstance(lbl, dict) else str(lbl) for lbl in data.get("labels", [])
        ],
        user=(data.get("user") or {}).get("login"),
        is_pull_request="pull_request" in data,
    )


def _pull(data: dict[str, Any]) -> PullRequest:
    return PullRequest(
        number=data["number"],
        title=data.get("title", ""),
        html_url=data.get("html_url", ""),
        state=data.get("state", ""),
        draft=bool(data.get("draft", False)),
        head=(data.get("head") or {}).get("ref", ""),
        base=(data.get("base") or {}).get("ref", ""),
    )
