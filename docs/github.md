# GitHub integration

## Components

- `integrations/github/client.py` — async REST client: repository metadata,
  issues, comments, branch refs, pull requests. **No merge method.**
- GitHub tools (`github` toolset) for agents that should read issues or open
  draft PRs themselves; restricted to `tool_settings.github.repositories`.
- `integrations/github/workflow.py` — the issue-to-pull-request workflow used
  by `agentforge github solve`.

## Issue → pull request workflow

```
GitHub issue ─► fetch issue + comments + default branch
             ─► clone (AgentForge, with token) into the run workspace
             ─► create branch agentforge/issue-<n>-<slug>
             ─► agent run (sandboxed, no token): analyse, implement, test, commit
             ─► evaluate: tests (--test-command) + "has commits"
             ─► commit leftovers (reported), count commits
             ─► [--push] push branch (only if run + evaluation succeeded,
                  unless --allow-failing)
             ─► [--open-pr] open a DRAFT pull request with run summary,
                  evaluation results and "Closes #<n>"
```

Guarantees:

- The token is used only by AgentForge's own git/HTTP calls (via an HTTP
  auth header, never in URLs or the agent's environment) and is redacted from
  every record.
- Nothing is pushed unless `--push` is given; PRs require `--open-pr` and are
  always drafts; nothing is ever merged.
- The run is labelled `github_repo`, `github_issue`, `branch` (and `pr_url`)
  so it can be found later.

## Usage

```bash
export GITHUB_TOKEN=...                       # fine-grained token: contents + pull requests (+ issues: read)
export ANTHROPIC_API_KEY=...
agentforge github repo owner/repo
agentforge github issues owner/repo -l bug
agentforge github solve owner/repo 42 \
  -a examples/agents/github-issue-solver.yaml \
  --test-command "pytest -q" \
  --push --open-pr
```

Without `--push` the branch stays in the local run workspace
(`.agentforge/workspaces/<run-id>`) for inspection.

## API and dashboard

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/github/status` | whether a token is configured (never returns it) |
| `GET /api/v1/github/repos/{owner}/{repo}` | repository metadata |
| `GET /api/v1/github/repos/{owner}/{repo}/issues` | issues (`state`, `labels`, `limit`) |
| `POST /api/v1/github/tasks` | start the workflow in the background: `{repo, issue_number, agent_id or config, base_branch?, test_command?, push, open_pr, allow_failing}` → the run record |
| `GET /api/v1/github/tasks` | runs created from issues |

The clone/push remote is always `https://github.com/<repo>.git`; it is not a
request parameter, because the token is sent to that remote. The dashboard's
*Repositories* page drives the same endpoints and *GitHub tasks* lists results
with branch, commit count and draft-PR link.
