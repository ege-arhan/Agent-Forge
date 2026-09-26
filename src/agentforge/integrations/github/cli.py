"""``agentforge github ...`` subcommands."""

from __future__ import annotations

import argparse
import os
from typing import Any


def register(sub: Any) -> None:
    github = sub.add_parser("github", help="GitHub integration").add_subparsers(
        dest="github_cmd", required=True
    )
    repo = github.add_parser("repo", help="show repository information")
    repo.add_argument("repo", help="owner/name")
    repo.set_defaults(handler=cmd_repo)

    issues = github.add_parser("issues", help="list open issues")
    issues.add_argument("repo", help="owner/name")
    issues.add_argument("-l", "--label", action="append")
    issues.add_argument("-n", "--limit", type=int, default=20)
    issues.set_defaults(handler=cmd_issues)

    solve = github.add_parser(
        "solve", help="run an agent on an issue; optionally push a branch and open a draft PR"
    )
    solve.add_argument("repo", help="owner/name")
    solve.add_argument("issue", type=int)
    solve.add_argument("-a", "--agent", required=True, help="agent config file")
    solve.add_argument("--base", help="base branch (default: repository default branch)")
    solve.add_argument("--test-command", help="command that must pass, e.g. 'pytest -q'")
    solve.add_argument("--push", action="store_true", help="push the branch to GitHub")
    solve.add_argument("--open-pr", action="store_true", help="open a draft PR (implies review)")
    solve.add_argument(
        "--allow-failing",
        action="store_true",
        help="push/open PR even if the run or evaluation failed",
    )
    solve.set_defaults(handler=cmd_solve)


def _token() -> str | None:
    from agentforge.settings import get_settings

    return os.environ.get(get_settings().github_token_env)


async def cmd_repo(args: argparse.Namespace) -> int:
    from agentforge.integrations.github.client import GitHubClient

    async with GitHubClient(_token()) as client:
        info = await client.get_repository(args.repo)
    for key, value in info.items():
        print(f"{key:<18} {value}")
    return 0


async def cmd_issues(args: argparse.Namespace) -> int:
    from agentforge.integrations.github.client import GitHubClient

    async with GitHubClient(_token()) as client:
        issues = await client.list_issues(args.repo, labels=args.label, limit=args.limit)
    for issue in issues:
        labels = f" [{', '.join(issue.labels)}]" if issue.labels else ""
        print(f"#{issue.number:<6} {issue.title}{labels}")
    return 0


async def cmd_solve(args: argparse.Namespace) -> int:
    from agentforge.cli import ConsoleObserver, _open_db, _run_summary
    from agentforge.config_files import load_agent_config
    from agentforge.integrations.github.client import GitHubClient
    from agentforge.integrations.github.workflow import IssueTaskRequest, solve_issue
    from agentforge.settings import get_settings
    from agentforge.storage import PersistenceObserver, RunRepository

    settings = get_settings()
    db = await _open_db(settings)
    runs = RunRepository(db)
    try:
        async with GitHubClient(_token()) as client:
            result = await solve_issue(
                IssueTaskRequest(
                    repo=args.repo,
                    issue_number=args.issue,
                    config=load_agent_config(args.agent),
                    base_branch=args.base,
                    test_command=args.test_command,
                    push=args.push,
                    open_pr=args.open_pr,
                    allow_failing=args.allow_failing,
                ),
                settings=settings,
                client=client,
                token=_token(),
                observers=[ConsoleObserver(), PersistenceObserver(runs)],
            )
        if result.pr_url:
            result.run.labels["pr_url"] = result.pr_url
            await runs.save(result.run)
    finally:
        await db.dispose()
    print(_run_summary(result.run))
    print(
        f"branch:     {result.branch} ({result.commits} commit(s) on top of {result.base_branch})"
    )
    print(f"workspace:  {result.run.workspace}")
    if result.pushed:
        print("pushed:     yes")
    if result.pr_url:
        print(f"draft PR:   {result.pr_url}  (requires human review; never auto-merged)")
    for note in result.notes:
        print(f"note:       {note}")
    return 0 if result.run.status.value == "succeeded" else 1
