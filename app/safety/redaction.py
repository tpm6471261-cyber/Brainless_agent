"""Shared recursive redaction for observability and durable metadata boundaries."""
from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEYS = ("password", "secret", "token", "api_key", "api key", "authorization",
                  "cookie", "credential", "session_key")
SENSITIVE_VALUE = re.compile(
    r"(?i)(password|passcode|api[_ -]?key|bearer|authorization|access[_ -]?token|secret|cookie)"
    r"\s*(?:is|=|:)?\s*[^\s,;]+"
)


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return SENSITIVE_VALUE.sub("[REDACTED]", value)
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if any(term in str(key).casefold()
                                              for term in SENSITIVE_KEYS) else redact(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value
