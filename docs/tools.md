# Tools

## Model

A tool is a class with:

| Attribute | Meaning |
|---|---|
| `name` | Identifier shown to the model (`^[a-zA-Z0-9_-]{1,64}$`) |
| `description` | What the tool does and when to use it |
| `input_model` | Pydantic model (subclass of `ToolInput`, which forbids unknown fields); its JSON schema is sent to the model |
| `permissions` | Set of `Permission` values the tool needs |
| `timeout_seconds` | Default executor timeout (overridable per agent: `tool_settings.<tool>.timeout_seconds`) |
| `run(args, ctx)` | Async execution returning `ToolOutput(content, is_error, data)`; raise `ToolError` for expected failures |

`ToolContext` gives the tool the run id, the `Workspace` (path confinement),
the `Sandbox` (command execution), the `Redactor`, per-agent `settings`
(`AgentConfig.tool_settings`), the memory store, the agent id and the process
environment (for credentials such as `GITHUB_TOKEN`; never passed to sandboxes).

## Execution pipeline (`ToolExecutor`)

For every tool call requested by the model:

1. Unknown tool → `invalid_input` result listing the available tools.
2. Malformed JSON arguments → `invalid_input`.
3. Permission check against `AGENTFORGE_DENIED_PERMISSIONS` → `denied`.
4. Pydantic validation → `invalid_input` with field-level messages (the model
   can correct itself).
5. Execution with timeout → `timeout`.
6. `ToolError`/`AgentForgeError` → `error`; unexpected exceptions → `error`
   with the traceback logged (not shown to the model).
7. Output redaction and head/tail truncation (`limits.max_output_chars`).
8. A `ToolCallRecord` with redacted arguments, status, output, duration.

Results go back to the model as tool results (`is_error` for non-success).

## Built-in tools

- **filesystem** — `read_file` (line-numbered, ranged), `write_file`,
  `edit_file` (exact snippet replacement, uniqueness enforced),
  `list_directory` (optionally recursive, skipping VCS/dependency dirs),
  `search_files` (regex, optional filename glob).
- **terminal** — `run_command` (`sh -c` in the sandbox; returns exit code,
  stdout, stderr; non-zero exit is a result, not a tool failure; timeouts kill
  the process tree). Settings: `command_timeout_seconds`,
  `max_command_timeout_seconds`.
- **git** — `git_status`, `git_diff`, `git_log`, `git_commit` (stage all or
  paths, then commit), `git_branch` (create/switch). Fixed argv, no shell,
  option-injection guarded.
- **http** — `http_request` (GET/HEAD/POST/PUT/PATCH/DELETE). Blocks private,
  loopback, link-local and other non-global addresses, re-checked on every
  redirect. Settings: `allowed_hosts` (supports `*.example.com`),
  `allow_private_networks`, `max_response_bytes`.
- **github** — repository metadata, list/get issues (with comments), comment,
  open a pull request (draft by default). Settings (`tool_settings.github`):
  `repositories` (required allowlist), `token_env`, `api_url`. No merge tool.
- **memory** — `remember` / `recall` against the agent's persistent memory.

## Writing a plugin tool

```python
from typing import ClassVar
from pydantic import Field
from agentforge.tools import Permission, Tool, ToolContext, ToolInput, ToolOutput


class WordCountInput(ToolInput):
    path: str = Field(description="File to count words in")


class WordCount(Tool[WordCountInput]):
    name = "word_count"
    description = "Count the words in a workspace file."
    input_model = WordCountInput
    permissions: ClassVar[frozenset[Permission]] = frozenset({Permission.FS_READ})
    timeout_seconds = 5.0

    async def run(self, args: WordCountInput, ctx: ToolContext) -> ToolOutput:
        text = ctx.workspace.resolve(args.path).read_text()
        return ToolOutput(content=str(len(text.split())))
```

Expose it from your package:

```toml
[project.entry-points."agentforge.tools"]
word_count = "my_package.tools:WordCount"
```

Plugin tools join the `plugins` toolset and can be listed by name in agent
configs.
