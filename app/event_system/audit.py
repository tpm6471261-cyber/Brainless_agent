"""Rotating structured audit logs with recursive secret redaction."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

SENSITIVE_KEYS = {"password", "passphrase", "token", "secret", "api_key", "credential", "clipboard", "text"}


def sanitize(value: Any, key: str = "") -> Any:
    if any(marker in key.casefold() for marker in SENSITIVE_KEYS): return "[REDACTED]"
    if is_dataclass(value): value = asdict(value)
    if isinstance(value, dict): return {str(k): sanitize(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)): return [sanitize(item) for item in value]
    if isinstance(value, datetime): return value.isoformat()
    return value


class StructuredEventLogger:
    def __init__(self, directory: str | Path, *, max_bytes: int = 2_000_000, backups: int = 3) -> None:
        directory = Path(directory); directory.mkdir(parents=True, exist_ok=True); self._logs = {}
        for name in ("event", "action", "security"):
            logger = logging.getLogger(f"brainless.audit.{name}.{id(self)}"); logger.setLevel(logging.INFO); logger.propagate = False
            logger.addHandler(RotatingFileHandler(directory / f"{name}.log", maxBytes=max_bytes, backupCount=backups, encoding="utf-8"))
            self._logs[name] = logger

    def write(self, stream: str, record: dict[str, Any]) -> None:
        if stream not in self._logs: raise ValueError(f"Unknown audit stream: {stream}")
        payload = {"timestamp": datetime.now(timezone.utc).isoformat(), **sanitize(record)}
        self._logs[stream].info(json.dumps(payload, sort_keys=True, default=str))

    def event(self, event, *, agent: str | None = None) -> None:
        self.write("event", {"event_id": event.event_id, "event_type": event.event_type,
            "source": event.source, "agent": agent, "severity": event.severity.value, "data": event.data})

    def action(self, name: str, result, *, agent: str | None = None, permission=(), risk: str | None = None) -> None:
        self.write("action", {"action": name, "agent": agent, "result": result.status.value,
            "permission": list(permission), "risk_level": risk, "duration": result.duration_ms, "error": result.error})

    def security(self, action: str, result: str, **metadata: Any) -> None:
        self.write("security", {"action": action, "result": result, **metadata})
