# AgentForge Development Status

Date: 2026-09-28

Version: **0.2.0** (released). Milestones 0–15 complete and merged into
`main`; milestone 16 (portfolio-quality release) is planned but not started.
See ROADMAP.md.

## Release state (verified this session)

- `main` is the repository's default branch, at `918f3bf` (merge of PR #11,
  which carries PR #12).
- PRs #8, #9, #10, #11 are merged; #12 shows merged as part of #11. No open
  pull requests.
- `v0.2.0` is tagged on `918f3bf` and published as a GitHub release (not a
  draft).
- CI and Security workflows are green on `main` at that commit (GitHub
  Actions API).
- No open Dependabot PRs against `main`.
- Not verifiable from a coding session: `main` branch protection rules (the
  GitHub API returns 403 for this session's token), OpenCode Go key rotation,
  and the "AgentForge daily development" / "Agent Forge" routine
  configuration (T-018) — see `docs/RELEASE_CHECKLIST.md`.

## This session's work

Added a native Gemini adapter (T-002b), removing the last "planned"
qualifier on milestone 2:

- `src/agentforge/llm/gemini.py`: speaks the Gemini `generateContent` REST
  API directly over `httpx` (already a core dependency), so no vendor SDK or
  optional extra is required. Handles role mapping (`user`/`model`), the
  separate `systemInstruction` field, function-call/response translation
  (Gemini has no per-call id, so one is synthesised on the way in and
  resolved back to a function name by a running id → name map on the way
  out), opaque "thought" parts echoed back verbatim, stop-reason mapping,
  and error classification. The API key is sent as the `x-goog-api-key`
  header, never the `?key=` query string.
- `llm/registry.py`: the `gemini` provider id now routes to `GeminiProvider`
  instead of the OpenAI-compatible Chat Completions shim.
- `llm/openai_compat.py`: the now-unused `gemini` preset removed.
- 15 new unit tests in `tests/unit/test_llm_providers.py` (message/tool
  translation, usage and stop-reason mapping, HTTP error classification,
  connection errors, registry wiring); all against a mocked `httpx`
  transport, no live API calls.
- `examples/agents/gemini.yaml`, `ARCHITECTURE.md` updated to match.

## Verification (2026-09-28)

- Python: 362 tests passing (`pytest -m "not docker"`, SQLite). Docker-sandbox
  tests deselected (no daemon in this session).
- `ruff check .`, `ruff format --check .`, `mypy` (strict): all clean.
- No API keys, tokens or other credentials introduced or logged; the Gemini
  adapter never puts its key in a URL or error message.

## Known limitations

- Real-model evidence (from v0.2.0) is small (one run per task); see
  `docs/REAL_MODEL_BENCHMARK.md`.
- The new Gemini adapter is unit-tested against a mocked transport only; it
  has not been exercised against the live Gemini API (no credentials or
  owner budget approval in this session).
- The approval gate runs in-process (single-node execution model).
- The regression gate compares against one baseline; trend baselines and
  richer policies are future work (T-019b).
- The rule-based improvement proposer changes configuration and prompt
  guidance only.
- The `agentforge-sandbox` image cannot be built in this development
  environment (Debian mirrors blocked); CI builds it.
- Databases created before migrations existed are rejected with a clear
  message; recreate them.
