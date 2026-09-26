"""GitHub integration."""

from agentforge.integrations.github.client import (
    GitHubClient,
    GitHubError,
    Issue,
    PullRequest,
    parse_repo,
)

__all__ = ["GitHubClient", "GitHubError", "Issue", "PullRequest", "parse_repo"]
