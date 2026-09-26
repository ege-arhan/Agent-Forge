from __future__ import annotations

import json
import logging

from agentforge.observability.logging import JsonFormatter
from agentforge.observability.redaction import REDACTED, Redactor


def test_known_secret_is_redacted() -> None:
    redactor = Redactor(["my-very-secret-token"])
    assert redactor.redact_text("token=my-very-secret-token!") == f"token={REDACTED}!"


def test_short_values_are_not_registered() -> None:
    redactor = Redactor(["abc"])
    assert redactor.redact_text("abc def") == "abc def"


def test_patterns_are_redacted() -> None:
    redactor = Redactor()
    samples = [
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz",
        "ghp_" + "a" * 36,
        "github_pat_" + "b" * 40,
        "AKIAABCDEFGHIJKLMNOP",
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123",
    ]
    for sample in samples:
        assert REDACTED in redactor.redact_text(sample), sample


def test_sensitive_keys_are_masked_recursively() -> None:
    redactor = Redactor()
    data = {"headers": {"Authorization": "xyz", "Accept": "json"}, "items": [{"api_key": "k"}]}
    out = redactor.redact(data)
    assert out["headers"]["Authorization"] == REDACTED
    assert out["headers"]["Accept"] == "json"
    assert out["items"][0]["api_key"] == REDACTED


def test_from_environment_picks_credential_like_names() -> None:
    redactor = Redactor.from_environment(
        {"MY_API_KEY": "value-1234567", "HOME": "/home/someone-long"}
    )
    assert redactor.redact_text("value-1234567 /home/someone-long") == f"{REDACTED} /home/someone-long"


def test_json_formatter_redacts_extra_fields() -> None:
    formatter = JsonFormatter(Redactor(["topsecret-value"]))
    record = logging.LogRecord("agentforge", logging.INFO, __file__, 1, "msg %s", ("x",), None)
    record.detail = "leak topsecret-value"
    payload = json.loads(formatter.format(record))
    assert payload["msg"] == "msg x"
    assert payload["detail"] == f"leak {REDACTED}"
