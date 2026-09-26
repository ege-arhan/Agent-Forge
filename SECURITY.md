# Security

AgentForge runs code written by language models. Treat every agent as
untrusted. This document describes the security model, the controls that
exist today, and their limits.

## Reporting vulnerabilities

Please report vulnerabilities privately via GitHub Security Advisories
("Report a vulnerability" on the repository's Security tab) rather than in a
public issue.

## Threat model

| Asset | Threat | Primary controls |
|---|---|---|
| Host machine | Agent runs destructive or malicious commands | Docker sandbox (no network, read-only root, dropped capabilities, resource limits, non-root user) |
| Provider/API keys, GitHub token | Exfiltration via tool output, logs, files or network | Scrubbed child environment, redaction of logs/records/tool output, no network in the Docker sandbox, token never given to the agent |
| Internal network | SSRF through the HTTP tool | Resolve-and-block of non-public addresses (incl. redirects), optional host allowlist, `network` permission deniable server-wide |
| Repositories | Unreviewed changes reach default branches | Branch-only pushes by AgentForge, draft PRs, **no merge capability anywhere** |
| API | Unauthorised use | Optional bearer API key, localhost-bound ports in Compose, CORS allowlist |

## Controls

### Sandboxes

- **Workspace confinement** (all tools): paths are resolved (following
  symlinks) and must stay inside the run's workspace.
- **Docker sandbox** (`sandbox.kind: docker`) — one container per run:
  `--network none` (default), `--read-only` root with a small `noexec` `/tmp`,
  `--cap-drop ALL`, `no-new-privileges`, memory/CPU/PID limits, host UID
  (non-root), per-command timeouts inside the container (`timeout -s KILL`)
  plus a host-side backstop, container removed after the run. Verified by
  `tests/integration/test_docker_sandbox.py` against a real daemon.
- **Local sandbox** (`sandbox.kind: local`) — **no isolation.** Commands run
  as host processes; only the working directory, a scrubbed environment and
  timeouts apply. A process running as the same user can still read files the
  AgentForge process can read (including `/proc/<pid>/environ` on Linux).
  Use it only for trusted development. Disable it on shared servers with
  `AGENTFORGE_ALLOW_LOCAL_SANDBOX=false`.

### Secrets

- Child processes receive only `PATH`, `LANG`, `LC_ALL`, `TZ`, `TERM`,
  `HOME=<workspace>` and explicit variables.
- `Redactor` masks registered secret values (every env var whose name looks
  like a key/token/secret/password) and common credential patterns in logs,
  tool arguments/outputs, persisted run records and memory.
- Agent configs reference keys by environment-variable *name*
  (`model.api_key_env`); keys are never stored.
- Redaction is defence in depth, not a guarantee: an agent that can read a
  secret can transform it (e.g. base64) before printing it. Do not place
  secrets where the agent can read them.

### Tools and permissions

Each tool declares permissions (`fs:read`, `fs:write`, `process:exec`,
`network`, `git:read`, `git:write`, `github:read`, `github:write`, `memory`).
Agents only get the tools listed in their config; operators can deny
permissions globally with `AGENTFORGE_DENIED_PERMISSIONS`. Tool inputs are
schema-validated; git tools use fixed argv (no shell) and reject option-like
paths and invalid ref names. GitHub tools require an explicit repository
allowlist.

### GitHub

AgentForge clones and pushes using the token; the agent only works on the
checkout inside its sandbox. Pushing and opening PRs are explicit opt-ins
(`--push`, `--open-pr`), pushes are skipped when the run or its evaluation
fails (unless `--allow-failing`), PRs are always drafts, and there is no merge
operation in the client, the tools or the workflow.

### Docker socket (Compose sandbox override)

`docker-compose.sandbox.yml` mounts the host Docker socket so the API can start
sandbox containers. Access to the Docker socket is equivalent to root on the
host. Use it only on machines you control, set `AGENTFORGE_API_KEY`, and do not
expose the API publicly. A rootless Docker or a dedicated sandbox host is
recommended for multi-user deployments.

## Known limitations / planned hardening

- No per-user authentication or authorisation (single shared API key).
- HTTP tool SSRF check is vulnerable to DNS rebinding between check and
  connect; mitigate with `allowed_hosts` and sandbox networking disabled.
- No egress proxy/allowlist for sandboxes that enable `network: bridge`.
- No gVisor/Firecracker option yet for stronger isolation.
- Rate limiting of the API is not implemented.

## Supply chain

CI runs `pip-audit` on the locked dependency set, ruff's bandit-derived `S`
rules, gitleaks secret scanning and CodeQL. Dependencies are pinned in
`uv.lock`; Dependabot proposes updates.
