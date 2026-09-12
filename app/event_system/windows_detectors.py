"""Opt-in Windows observers built on documented Win32 and PowerShell APIs.

The collectors in this module deliberately keep acquisition separate from event
normalization.  Each detector accepts a reader, which makes it useful as an agent
building block and lets non-Windows CI exercise the state machines without
pretending that a native capability exists.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Callable, Mapping

from app.event_system.models import Event, EventSeverity


def _windows_only(feature: str) -> None:
    if sys.platform != "win32":
        raise RuntimeError(f"{feature} is available only on Windows")


def _powershell_json(script: str) -> Any:
    """Run a fixed, non-interactive PowerShell inventory query."""
    _windows_only("PowerShell inventory")
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True, capture_output=True, text=True, timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = completed.stdout.strip()
    return json.loads(output) if output else []


@dataclass(frozen=True, slots=True)
class KeyboardPrivacyFilter:
    """Controls keyboard metadata exposure; typed text is suppressed by default."""

    expose_printable_keys: bool = False
    blocked_processes: frozenset[str] = frozenset()
    blocked_window_terms: frozenset[str] = frozenset({"password", "credential", "sign in", "login"})

    def protect(self, key: str, *, process: str | None, window: str | None) -> str:
        sensitive = ((process or "").casefold() in {x.casefold() for x in self.blocked_processes}
                     or any(term.casefold() in (window or "").casefold() for term in self.blocked_window_terms))
        printable = len(key) == 1
        return "[REDACTED]" if sensitive or (printable and not self.expose_printable_keys) else key


class KeyboardDetector:
    """Poll key transitions with GetAsyncKeyState; no keystroke contents are stored."""

    name = "keyboard"
    _KEYS = {
        0x08: "BACKSPACE", 0x09: "TAB", 0x0D: "ENTER", 0x10: "SHIFT", 0x11: "CTRL",
        0x12: "ALT", 0x14: "CAPSLOCK", 0x1B: "ESCAPE", 0x20: "SPACE", 0x21: "PAGEUP",
        0x22: "PAGEDOWN", 0x23: "END", 0x24: "HOME", 0x25: "LEFT", 0x26: "UP",
        0x27: "RIGHT", 0x28: "DOWN", 0x2D: "INSERT", 0x2E: "DELETE", 0x5B: "WIN",
        0x90: "NUMLOCK", 0x91: "SCROLLLOCK",
        **{code: chr(code) for code in range(0x30, 0x3A)},
        **{code: chr(code) for code in range(0x41, 0x5B)},
        **{0x70 + index: f"F{index + 1}" for index in range(24)},
    }
    _MODIFIERS = frozenset({"CTRL", "ALT", "SHIFT", "WIN"})

    def __init__(self, reader: Callable[[], Mapping[str, Any]] | None = None, *,
                 privacy: KeyboardPrivacyFilter | None = None,
                 context_reader: Callable[[], tuple[str | None, str | None]] | None = None) -> None:
        self.reader = reader or self._read_windows
        self.privacy = privacy or KeyboardPrivacyFilter()
        self.context_reader = context_reader or (lambda: (None, None))
        self._pressed: frozenset[str] = frozenset()

    @classmethod
    def _read_windows(cls) -> Mapping[str, bool]:
        _windows_only("Keyboard observation")
        get_state = ctypes.windll.user32.GetAsyncKeyState
        return {name: bool(get_state(code) & 0x8000) for code, name in cls._KEYS.items()}

    async def poll(self) -> tuple[Event, ...]:
        state = self.reader()
        pressed = frozenset(key.upper() for key, value in state.items() if value)
        process, window = self.context_reader()
        events: list[Event] = []
        for key in sorted(pressed - self._pressed):
            safe_key = self.privacy.protect(key, process=process, window=window)
            events.append(self._event("ON_KEY_DOWN", safe_key, pressed, process, window))
            events.append(self._event("ON_KEY_PRESS", safe_key, pressed, process, window))
        for key in sorted(self._pressed - pressed):
            events.append(self._event("ON_KEY_UP", self.privacy.protect(key, process=process, window=window),
                                      pressed, process, window))
        if (pressed & self._MODIFIERS) != (self._pressed & self._MODIFIERS):
            events.append(Event("ON_MODIFIER_CHANGED", "keyboard", self.name, process=process, window=window,
                data={"modifiers": sorted(pressed & self._MODIFIERS)},
                permissions_required=frozenset({"keyboard.observe"})))
        newly_pressed = pressed - self._pressed
        if newly_pressed and pressed & self._MODIFIERS:
            events.append(Event("ON_HOTKEY", "keyboard", self.name, process=process, window=window,
                data={"keys": sorted(self.privacy.protect(k, process=process, window=window) for k in pressed)},
                permissions_required=frozenset({"keyboard.observe"})))
        self._pressed = pressed
        return tuple(events)

    @staticmethod
    def _event(kind: str, key: str, pressed: frozenset[str], process: str | None, window: str | None) -> Event:
        return Event(kind, "keyboard", "keyboard", process=process, window=window,
            data={"key": key, "modifiers": sorted(pressed & KeyboardDetector._MODIFIERS)},
            permissions_required=frozenset({"keyboard.observe"}))


class MouseDetector:
    """Observe pointer/buttons and derive move, enter/leave, drag and double-click events."""

    name = "mouse"

    def __init__(self, reader: Callable[[], Mapping[str, Any]] | None = None, *,
                 double_click_seconds: float = .5, clock: Callable[[], float] = monotonic) -> None:
        self.reader = reader or self._read_windows
        self.double_click_seconds = double_click_seconds
        self.clock = clock
        self.previous: dict[str, Any] | None = None
        self._dragging: str | None = None
        self._last_click: dict[str, float] = {}

    @staticmethod
    def _read_windows() -> Mapping[str, Any]:
        _windows_only("Mouse observation")
        point = wintypes.POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            raise OSError("GetCursorPos failed")
        get_state = ctypes.windll.user32.GetAsyncKeyState
        hwnd = ctypes.windll.user32.WindowFromPoint(point)
        return {"x": point.x, "y": point.y, "screen": 0, "target_window": str(hwnd) if hwnd else None,
                "target_process": None, "buttons": {"left": bool(get_state(0x01) & 0x8000),
                "right": bool(get_state(0x02) & 0x8000), "middle": bool(get_state(0x04) & 0x8000)}}

    async def poll(self) -> tuple[Event, ...]:
        current = dict(self.reader()); current["buttons"] = dict(current.get("buttons", {}))
        old = self.previous; self.previous = current
        if old is None:
            return (self._event("ON_MOUSE_POSITION_CHANGED", current),)
        events: list[Event] = []
        moved = (current.get("x"), current.get("y")) != (old.get("x"), old.get("y"))
        if moved:
            events.extend((self._event("ON_MOUSE_MOVE", current), self._event("ON_MOUSE_POSITION_CHANGED", current)))
        if current.get("target_window") != old.get("target_window"):
            if old.get("target_window"): events.append(self._event("ON_MOUSE_LEAVE", old))
            if current.get("target_window"): events.append(self._event("ON_MOUSE_ENTER", current))
        for button in ("left", "right", "middle"):
            down, was_down = bool(current["buttons"].get(button)), bool(old.get("buttons", {}).get(button))
            if down and not was_down:
                events.append(self._event(f"ON_MOUSE_{button.upper()}_DOWN", current, button))
                now = self.clock()
                if now - self._last_click.get(button, -1e9) <= self.double_click_seconds:
                    events.append(self._event("ON_MOUSE_DOUBLE_CLICK", current, button))
                self._last_click[button] = now
            if not down and was_down:
                events.append(self._event(f"ON_MOUSE_{button.upper()}_UP", current, button))
                if self._dragging == button:
                    events.append(self._event("ON_MOUSE_DRAG_END", current, button)); self._dragging = None
            if moved and down:
                if self._dragging != button:
                    self._dragging = button; events.append(self._event("ON_MOUSE_DRAG_START", current, button))
                events.append(self._event("ON_MOUSE_DRAG", current, button))
        return tuple(events)

    @staticmethod
    def _event(kind: str, state: Mapping[str, Any], button: str | None = None) -> Event:
        data = {key: state.get(key) for key in ("x", "y", "screen", "target_window", "target_process")}
        if button: data["button"] = button
        return Event(kind, "mouse", "mouse", process=state.get("target_process"),
            window=state.get("target_window"), data=data,
            permissions_required=frozenset({"mouse.observe"}))


class DeviceDetector:
    """Poll present PnP devices and emit safe class-level connection transitions."""

    name = "device"
    _CLASS_EVENTS = {"keyboard": "KEYBOARD", "mouse": "MOUSE", "camera": "CAMERA",
        "audioendpoint": "AUDIO_DEVICE", "bluetooth": "BLUETOOTH", "diskdrive": "EXTERNAL_DRIVE",
        "usb": "USB", "phone": "PHONE", "media": "AUDIO_DEVICE"}

    def __init__(self, reader: Callable[[], Mapping[str, Mapping[str, Any]]] | None = None) -> None:
        self.reader = reader or self._read_windows; self.previous: dict[str, Mapping[str, Any]] = {}

    @staticmethod
    def _read_windows() -> Mapping[str, Mapping[str, Any]]:
        rows = _powershell_json("Get-PnpDevice -PresentOnly | Select-Object InstanceId,Class,FriendlyName,Status | ConvertTo-Json -Compress")
        if isinstance(rows, dict): rows = [rows]
        return {row["InstanceId"]: {"device_class": row.get("Class"), "name": row.get("FriendlyName"),
                "status": row.get("Status")} for row in rows}

    async def poll(self) -> tuple[Event, ...]:
        current = dict(self.reader()); events = []
        for device_id, metadata in current.items():
            if device_id not in self.previous: events.extend(self._events(True, device_id, metadata))
        for device_id, metadata in self.previous.items():
            if device_id not in current: events.extend(self._events(False, device_id, metadata))
        self.previous = current
        return tuple(events)

    def _events(self, connected: bool, device_id: str, metadata: Mapping[str, Any]) -> tuple[Event, ...]:
        suffix = "CONNECTED" if connected else "DISCONNECTED"
        safe = {"device_id": hashlib.sha256(device_id.encode()).hexdigest()[:16], "device_class": metadata.get("device_class"),
                "name": metadata.get("name"), "status": metadata.get("status")}
        specific = self._CLASS_EVENTS.get(str(metadata.get("device_class", "")).casefold())
        names = [f"ON_DEVICE_{suffix}"] + ([f"ON_{specific}_{suffix}"] if specific else [])
        return tuple(Event(name, "device", self.name, data=safe,
            permissions_required=frozenset({"device.observe"})) for name in names)


class AudioDetector(DeviceDetector):
    """Use the Windows AudioEndpoint inventory for connect/disconnect observation."""

    name = "audio"

    @staticmethod
    def _read_windows() -> Mapping[str, Mapping[str, Any]]:
        rows = _powershell_json("Get-PnpDevice -Class AudioEndpoint -PresentOnly | Select-Object InstanceId,FriendlyName,Status | ConvertTo-Json -Compress")
        if isinstance(rows, dict): rows = [rows]
        return {row["InstanceId"]: {"device_class": "AudioEndpoint", "name": row.get("FriendlyName"),
                "status": row.get("Status")} for row in rows}

    def _events(self, connected: bool, device_id: str, metadata: Mapping[str, Any]) -> tuple[Event, ...]:
        suffix = "CONNECTED" if connected else "DISCONNECTED"
        safe_id = hashlib.sha256(device_id.encode()).hexdigest()[:16]
        return (Event(f"ON_AUDIO_DEVICE_{suffix}", "audio", self.name,
            data={"device_id": safe_id, **dict(metadata)}, permissions_required=frozenset({"audio.observe"})),
            Event("ON_AUDIO_DEVICE_CHANGED", "audio", self.name,
            data={"device_id": safe_id, "connected": connected, **dict(metadata)},
            permissions_required=frozenset({"audio.observe"})))


class SessionDetector:
    """Normalize WTS session inventory changes without collecting user content."""

    name = "session"

    def __init__(self, reader: Callable[[], Mapping[str, Mapping[str, Any]]] | None = None) -> None:
        self.reader = reader or self._read_windows; self.previous: dict[str, Mapping[str, Any]] = {}

    @staticmethod
    def _read_windows() -> Mapping[str, Mapping[str, Any]]:
        rows = _powershell_json("Get-CimInstance Win32_LogonSession | Select-Object LogonId,LogonType,StartTime | ConvertTo-Json -Compress")
        if isinstance(rows, dict): rows = [rows]
        return {str(row["LogonId"]): {"session_id": str(row["LogonId"]), "logon_type": row.get("LogonType"),
                "start_time": row.get("StartTime")} for row in rows}

    async def poll(self) -> tuple[Event, ...]:
        current = dict(self.reader()); events = []
        for key, value in current.items():
            if key not in self.previous: events.append(self._event("ON_USER_LOGIN", value))
            elif value != self.previous[key]: events.append(self._event("ON_SESSION_CHANGED", value))
        for key, value in self.previous.items():
            if key not in current: events.append(self._event("ON_USER_LOGOUT", value))
        self.previous = current
        return tuple(events)

    def _event(self, event_type: str, data: Mapping[str, Any]) -> Event:
        return Event(event_type, "system", self.name, data=dict(data),
            permissions_required=frozenset({"session.observe"}))


class NotificationDetector:
    """Observe dialog/toast windows through an injected/native safe window inventory."""

    name = "notifications"

    def __init__(self, reader: Callable[[], Mapping[str, Mapping[str, Any]]] | None = None) -> None:
        self.reader = reader or self._read_windows; self.previous: set[str] = set()

    @staticmethod
    def _read_windows() -> Mapping[str, Mapping[str, Any]]:
        _windows_only("Notification observation")
        import pygetwindow
        result = {}
        for window in pygetwindow.getAllWindows():
            title = str(window.title or "")
            if title:
                result[str(getattr(window, "_hWnd", title))] = {"title": title, "application": None}
        return result

    async def poll(self) -> tuple[Event, ...]:
        current = dict(self.reader()); events = []
        for key, metadata in current.items():
            if key in self.previous: continue
            title = str(metadata.get("title", "")); lowered = title.casefold()
            kind = ("ON_PERMISSION_DIALOG" if "permission" in lowered else "ON_ERROR_DIALOG" if "error" in lowered
                    else "ON_WARNING_DIALOG" if "warning" in lowered else "ON_NOTIFICATION")
            events.append(Event(kind, "notification", self.name, window=title,
                data={"application": metadata.get("application"), "title": title,
                      "notification_type": kind.removeprefix("ON_").casefold()},
                permissions_required=frozenset({"notification.observe"})))
        self.previous = set(current)
        return tuple(events)


def create_windows_detectors(*, keyboard: bool = False, mouse: bool = False,
                             devices: bool = True, audio: bool = True,
                             sessions: bool = True, notifications: bool = False,
                             privacy: KeyboardPrivacyFilter | None = None) -> tuple[object, ...]:
    """Build opt-in detector instances for composition into an ``EventManager``."""
    detectors: list[object] = []
    if keyboard: detectors.append(KeyboardDetector(privacy=privacy))
    if mouse: detectors.append(MouseDetector())
    if devices: detectors.append(DeviceDetector())
    if audio: detectors.append(AudioDetector())
    if sessions: detectors.append(SessionDetector())
    if notifications: detectors.append(NotificationDetector())
    return tuple(detectors)
