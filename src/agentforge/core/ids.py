"""Identifier and time helpers.

IDs are prefixed and roughly time-sortable (millisecond timestamp followed by
random bytes) so that listing by ID approximates listing by creation time and
IDs are self-describing in logs (``run_...``, ``agt_...``).
"""

from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime


def new_id(prefix: str) -> str:
    """Return a new identifier such as ``run_0192f3a1b2c3d4e5f6a7b8c9``."""
    millis = int(time.time() * 1000)
    return f"{prefix}_{millis:012x}{secrets.token_hex(6)}"


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(UTC)
