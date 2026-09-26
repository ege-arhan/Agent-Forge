"""GitHub tools.

Settings (``tool_settings.github``)::

    repositories: [owner/repo]   # required allowlist - tools refuse other repos
    token_env: GITHUB_TOKEN      # env var holding the token (never logged)
    api_url: https://api.github.com

Pull requests are opened as drafts by default and there is no merge tool:
human review is always required.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
from pydantic import Field

from agentforge.core.errors import PermissionDeniedError, ToolError
from agentforge.integrations.github.client import API_URL, GitHubClient, GitHubError
from agentforge.tools.base import Permission, Tool, ToolContext, ToolInput, ToolOutput


class _GitHubTool[InputT: ToolInput](Tool[InputT]):
    #: Overridable in tests.
    transport: ClassVar[httpx.AsyncBaseTransport | None] = None

    def _client(self, ctx: ToolContext, repo: str) -> GitHubClient:
        settings: dict[str, Any] = ctx.settings.get("github", {})
        allowed = [r.lower() for r in settings.get("repositories", [])]
        if repo.lower() not in allowed:
            raise PermissionDeniedError(
                f"repository '{repo}' is not in tool_settings.github.repositories"
            )
        token = ctx.env.get(settings.get("token_env", "GITHUB_TOKEN"))
        ctx.redactor.add_secret(token)
        return GitHubClient(
            token, base_url=settings.get("api_url", API_URL), transport=self.transport
        )


class RepoInput(ToolInput):
    repo: str = Field(description="Repository as owner/name.")


class GitHubGetRepository(_GitHubTool[RepoInput]):
    name = "github_get_repository"
    description = "Get repository metadata (default branch, language, description, ...)."
    input_model = RepoInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.GITHUB_READ})

    async def run(self, args: RepoInput, ctx: ToolContext) -> ToolOutput:
        try:
            async with self._client(ctx, args.repo) as client:
                data = await client.get_repository(args.repo)
        except GitHubError as exc:
            raise ToolError(exc.message) from exc
        return ToolOutput(content="\n".join(f"{k}: {v}" for k, v in data.items()), data=data)


class ListIssuesInput(RepoInput):
    state: str = Field(default="open", pattern="^(open|closed|all)$")
    labels: list[str] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=100)


class GitHubListIssues(_GitHubTool[ListIssuesInput]):
    name = "github_list_issues"
    description = "List issues (not pull requests) in a repository."
    input_model = ListIssuesInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.GITHUB_READ})

    async def run(self, args: ListIssuesInput, ctx: ToolContext) -> ToolOutput:
        try:
            async with self._client(ctx, args.repo) as client:
                issues = await client.list_issues(
                    args.repo, state=args.state, labels=args.labels, limit=args.limit
                )
        except GitHubError as exc:
            raise ToolError(exc.message) from exc
        lines = [f"#{i.number} [{i.state}] {i.title} ({', '.join(i.labels)})" for i in issues]
        return ToolOutput(content="\n".join(lines) or "no issues")


class IssueInput(RepoInput):
    number: int = Field(ge=1)


class GitHubGetIssue(_GitHubTool[IssueInput]):
    name = "github_get_issue"
    description = "Get an issue's title, body, labels and comments."
    input_model = IssueInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.GITHUB_READ})

    async def run(self, args: IssueInput, ctx: ToolContext) -> ToolOutput:
        try:
            async with self._client(ctx, args.repo) as client:
                issue = await client.get_issue(args.repo, args.number)
                comments = await client.list_issue_comments(args.repo, args.number)
        except GitHubError as exc:
            raise ToolError(exc.message) from exc
        text = (
            f"#{issue.number} {issue.title}\nstate: {issue.state}\n"
            f"labels: {', '.join(issue.labels) or '-'}\nurl: {issue.html_url}\n\n"
            f"{issue.body or '(no description)'}"
        )
        if comments:
            text += "\n\nComments:\n" + "\n---\n".join(comments)
        return ToolOutput(content=text)


class CommentInput(IssueInput):
    body: str = Field(min_length=1, max_length=60_000)


class GitHubCommentIssue(_GitHubTool[CommentInput]):
    name = "github_comment_issue"
    description = "Post a comment on an issue or pull request."
    input_model = CommentInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.GITHUB_WRITE})

    async def run(self, args: CommentInput, ctx: ToolContext) -> ToolOutput:
        try:
            async with self._client(ctx, args.repo) as client:
                url = await client.create_issue_comment(args.repo, args.number, args.body)
        except GitHubError as exc:
            raise ToolError(exc.message) from exc
        return ToolOutput(content=f"comment posted: {url}")


class CreatePullRequestInput(RepoInput):
    title: str = Field(min_length=1, max_length=256)
    head: str = Field(description="Branch containing the changes (must already be pushed).")
    base: str = Field(description="Branch to merge into, usually the default branch.")
    body: str = Field(default="", max_length=60_000)
    draft: bool = True


class GitHubCreatePullRequest(_GitHubTool[CreatePullRequestInput]):
    name = "github_create_pull_request"
    description = (
        "Open a pull request (draft by default). Pull requests are never merged automatically; "
        "a human must review them."
    )
    input_model = CreatePullRequestInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.GITHUB_WRITE})

    async def run(self, args: CreatePullRequestInput, ctx: ToolContext) -> ToolOutput:
        try:
            async with self._client(ctx, args.repo) as client:
                pr = await client.create_pull_request(
                    args.repo,
                    title=args.title,
                    head=args.head,
                    base=args.base,
                    body=args.body,
                    draft=args.draft,
                )
        except GitHubError as exc:
            raise ToolError(exc.message) from exc
        return ToolOutput(
            content=f"opened {'draft ' if pr.draft else ''}PR #{pr.number}: {pr.html_url}",
            data=pr.model_dump(),
        )


GITHUB_TOOLS: list[type[Tool[Any]]] = [
    GitHubGetRepository,
    GitHubListIssues,
    GitHubGetIssue,
    GitHubCommentIssue,
    GitHubCreatePullRequest,
]
