"""Composition helpers for embedding the event platform in future agents."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.event_system.actions import ActionRegistry
from app.event_system.bus import EventBus, EventManager
from app.event_system.config import EventSystemConfig
from app.event_system.detectors import (ClipboardDetector, DisplayDetector, FilesystemDetector,
    MousePositionDetector, NetworkDetector, PowerDetector, ProcessDetector, ResourceDetector,
    SchedulerDetector, WindowDetector)
from app.event_system.native_actions import register_desktop_actions
from app.event_system.windows_detectors import KeyboardPrivacyFilter, create_windows_detectors


@dataclass(slots=True)
class EventPlatform:
    """Owned set of event/action services that can be attached to an agent runtime."""

    config: EventSystemConfig
    bus: EventBus
    manager: EventManager
    actions: ActionRegistry

    def emergency_stop(self) -> None:
        self.actions.emergency_stop(); self.bus.pause()

    async def resume(self) -> None:
        self.actions.resume(); await self.bus.resume()


def create_event_platform(config: EventSystemConfig | None = None, *, confirm=None,
                          keyboard_privacy: KeyboardPrivacyFilter | None = None) -> EventPlatform:
    """Build the enabled, safe-by-default observers and permission action boundary."""
    config = config or EventSystemConfig()
    bus = EventBus()
    actions = ActionRegistry(dry_run=config.dry_run, confirm=confirm)
    register_desktop_actions(actions)
    detectors: list[object] = [ResourceDetector(), SchedulerDetector(), NetworkDetector(),
                               ProcessDetector(), PowerDetector()]
    if config.filesystem_enabled:
        paths = config.watch_paths or (Path.home() / "Desktop", Path.home() / "Downloads",
                                       Path.home() / "Documents", Path.home() / "Pictures", Path.home() / "Videos")
        detectors.append(FilesystemDetector(paths))
    if config.screen_observation: detectors.append(DisplayDetector())
    if config.clipboard_observation: detectors.append(ClipboardDetector(enabled=True))
    if config.mouse_observation: detectors.append(MousePositionDetector())
    detectors.extend(create_windows_detectors(keyboard=config.keyboard_observation,
        mouse=config.mouse_button_observation, devices=config.device_observation,
        audio=config.audio_observation, sessions=config.session_observation,
        notifications=config.notification_observation, privacy=keyboard_privacy))
    if config.window_observation: detectors.append(WindowDetector())
    return EventPlatform(config, bus, EventManager(bus, detectors if config.enabled else ()), actions)
