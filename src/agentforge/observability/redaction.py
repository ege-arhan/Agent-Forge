"""Secret redaction for logs, traces and persisted run records.

Two complementary mechanisms:

* **known values** - secrets AgentForge itself holds (API keys, tokens read
  from the environment) are registered and replaced verbatim wherever they
  appear;
* **patterns** - common credential formats and sensitive field names are
  masked even when the value was never registered (e.g. a token the agent
  read from a file).

Redaction is best-effort defence in depth; it does not make it safe to hand
untrusted agents real credentials.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from typing import Any

REDACTED = "[REDACTED]"

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),  # Anthropic
    re.compile(r"sk-(?:proj-|or-v1-)?[A-Za-z0-9_\-]{20,}"),  # OpenAI / OpenRouter
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub tokens
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),  # Google API keys
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"),  # Slack
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]

_SENSITIVE_KEY = re.compile(
    r"(?i)(api[_-]?key|secret|password|passwd|token|authorization|credential|private[_-]?key)"
)

_SECRET_ENV_HINT = re.compile(r"(?i)(KEY|TOKEN|SECRET|PASSWORD)")

# Values shorter than this are not registered to avoid redacting common words.
_MIN_SECRET_LEN = 8


class Redactor:
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets: set[str] = set()
        for secret in secrets:
            self.add_secret(secret)

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> Redactor:
        """Register every env var value whose name looks like a credential."""
        env = os.environ if env is None else env
        return cls(value for name, value in env.items() if _SECRET_ENV_HINT.search(name))

    def add_secret(self, value: str | None) -> None:
        if value and len(value) >= _MIN_SECRET_LEN:
            self._secrets.add(value)

    def redact_text(self, text: str) -> str:
        if not text:
            return text
        # Longest first so a secret containing another is fully masked.
        for secret in sorted(self._secrets, key=len, reverse=True):
            if secret in text:
                text = text.replace(secret, REDACTED)
        for pattern in _PATTERNS:
            text = pattern.sub(REDACTED, text)
        return text

    def redact(self, value: Any) -> Any:
        """Recursively redact strings inside dicts/lists; mask sensitive keys."""
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, Mapping):
            out: dict[Any, Any] = {}
            for key, item in value.items():
                if isinstance(key, str) and _SENSITIVE_KEY.search(key) and isinstance(item, str):
                    out[key] = REDACTED if item else item
                else:
                    out[key] = self.redact(item)
            return out
        if isinstance(value, list | tuple):
            return [self.redact(item) for item in value]
        return value
