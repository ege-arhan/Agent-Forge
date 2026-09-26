"""Structured JSON logging with secret redaction."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from agentforge.observability.redaction import Redactor

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message"}


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects.

    Extra fields passed via ``logger.info("...", extra={...})`` are included.
    All string content is passed through the redactor.
    """

    def __init__(self, redactor: Redactor | None = None) -> None:
        super().__init__()
        self._redactor = redactor or Redactor()

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(self._redactor.redact(payload), default=str)


class TextFormatter(logging.Formatter):
    def __init__(self, redactor: Redactor | None = None) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        self._redactor = redactor or Redactor()

    def format(self, record: logging.LogRecord) -> str:
        return self._redactor.redact_text(super().format(record))


def configure_logging(
    level: str = "INFO", *, json_format: bool = True, redactor: Redactor | None = None
) -> None:
    redactor = redactor or Redactor.from_environment()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter(redactor) if json_format else TextFormatter(redactor))
    root = logging.getLogger("agentforge")
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    root.propagate = False
