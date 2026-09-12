"""Safe-by-default configuration for desktop observation and control."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _boolean(value: object, default: bool = False) -> bool:
    if value is None: return default
    if isinstance(value, bool): return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class EventSystemConfig:
    enabled: bool = True
    dry_run: bool = False
    keyboard_observation: bool = False
    clipboard_observation: bool = False
    mouse_observation: bool = False
    mouse_button_observation: bool = False
    window_observation: bool = True
    device_observation: bool = False
    audio_observation: bool = False
    session_observation: bool = False
    notification_observation: bool = False
    screen_observation: bool = True
    filesystem_enabled: bool = True
    browser_enabled: bool = True
    require_confirmation: bool = True
    logging_enabled: bool = True
    emergency_stop_enabled: bool = True
    watch_paths: tuple[Path, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, values: dict[str, Any] | None = None) -> "EventSystemConfig":
        values = values or {}; event = values.get("event_system", {}); security = values.get("security", {})
        return cls(enabled=_boolean(event.get("enabled"), True),
            dry_run=_boolean(os.getenv("DRY_RUN", event.get("dry_run"))),
            keyboard_observation=_boolean(values.get("keyboard", {}).get("observation")),
            clipboard_observation=_boolean(values.get("clipboard", {}).get("observation")),
            mouse_observation=_boolean(values.get("mouse", {}).get("observation")),
            mouse_button_observation=_boolean(values.get("mouse", {}).get("button_observation")),
            window_observation=_boolean(values.get("window", {}).get("observation"), True),
            device_observation=_boolean(values.get("devices", {}).get("observation")),
            audio_observation=_boolean(values.get("audio", {}).get("observation")),
            session_observation=_boolean(values.get("session", {}).get("observation")),
            notification_observation=_boolean(values.get("notifications", {}).get("observation")),
            screen_observation=_boolean(values.get("screen", {}).get("observation"), True),
            filesystem_enabled=_boolean(values.get("filesystem", {}).get("enabled"), True),
            browser_enabled=_boolean(values.get("browser", {}).get("enabled"), True),
            require_confirmation=_boolean(security.get("require_confirmation"), True),
            logging_enabled=_boolean(values.get("logging", {}).get("enabled"), True),
            emergency_stop_enabled=_boolean(values.get("emergency_stop", {}).get("enabled"), True),
            watch_paths=tuple(Path(path).expanduser() for path in values.get("filesystem", {}).get("paths", ())))
