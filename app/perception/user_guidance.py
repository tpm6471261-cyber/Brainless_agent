"""Explicit user-selected screen regions exposed as perception data, never actions."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Protocol
from uuid import uuid4

from app.perception.models import PerceptionObservation, UIElement

ALLOWED_ROLES = frozenset({"button", "textbox", "link", "checkbox", "radio", "tab",
                           "menu", "dialog", "image", "text", "other"})


@dataclass(frozen=True, slots=True)
class ScreenRegion:
    bounds: tuple[int, int, int, int]
    screen_dimensions: tuple[int, int]
    screenshot_reference: str


class RegionSelector(Protocol):
    def select(self, output_dir: Path, timeout_seconds: int) -> ScreenRegion: ...


class DesktopRegionSelector:
    """Display a local desktop overlay and capture the owner's selected region."""

    def select(self, output_dir: Path, timeout_seconds: int = 20) -> ScreenRegion:
        # Imported only for an authenticated request, so headless startup remains usable.
        import tkinter as tk
        import pyautogui
        from PIL import ImageDraw

        width, height = pyautogui.size()
        root = tk.Tk()
        root.title("Brainless Agent — select an area (Esc to cancel)")
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.28)
        root.overrideredirect(True)
        root.geometry(f"{width}x{height}+0+0")
        canvas = tk.Canvas(root, cursor="crosshair", bg="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        start: list[int] = []
        selected: list[tuple[int, int, int, int]] = []
        rectangle: list[int] = []

        def cancel(_event=None) -> None:
            root.quit()

        def pressed(event) -> None:
            start[:] = [event.x, event.y]
            rectangle[:] = [canvas.create_rectangle(
                event.x, event.y, event.x, event.y, outline="#50d5c8", width=4)]

        def dragged(event) -> None:
            if start and rectangle:
                canvas.coords(rectangle[0], start[0], start[1], event.x, event.y)

        def released(event) -> None:
            if not start:
                return
            left, right = sorted((start[0], event.x))
            top, bottom = sorted((start[1], event.y))
            if right - left >= 4 and bottom - top >= 4:
                selected.append((left, top, right - left, bottom - top))
                root.quit()

        canvas.bind("<ButtonPress-1>", pressed)
        canvas.bind("<B1-Motion>", dragged)
        canvas.bind("<ButtonRelease-1>", released)
        root.bind("<Escape>", cancel)
        root.after(timeout_seconds * 1000, cancel)
        root.mainloop()
        root.destroy()
        if not selected:
            raise TimeoutError("Screen selection was cancelled or timed out")

        output_dir.mkdir(parents=True, exist_ok=True)
        screenshot = pyautogui.screenshot()
        left, top, region_width, region_height = selected[0]
        ImageDraw.Draw(screenshot).rectangle(
            (left, top, left + region_width, top + region_height), outline="#00d8c8", width=5)
        path = output_dir / f"user-guidance-{uuid4().hex}.png"
        screenshot.save(path)
        return ScreenRegion(selected[0], (width, height), str(path.resolve()))


class UserGuidancePerceptionSource:
    """Store one bounded owner-provided semantic hint for the fusion engine."""

    name = "user_guidance"
    capabilities = frozenset({"screen.read"})

    def __init__(self, output_dir: Path, selector: RegionSelector | None = None,
                 timeout_seconds: int = 20) -> None:
        self.output_dir = output_dir
        self.selector = selector or DesktopRegionSelector()
        self.timeout_seconds = timeout_seconds
        self._latest: PerceptionObservation | None = None
        self._lock = Lock()

    @property
    def available(self) -> bool:
        """Do not degrade unrelated observations before the owner provides a hint."""
        with self._lock:
            return self._latest is not None

    async def select(self, label: str, role: str) -> UIElement:
        label = label.strip()
        role = role.strip().casefold()
        if not label or len(label) > 200:
            raise ValueError("Guidance label is required and must be at most 200 characters")
        if role not in ALLOWED_ROLES:
            raise ValueError("Unsupported guidance role")
        region = await asyncio.to_thread(self.selector.select, self.output_dir, self.timeout_seconds)
        element = UIElement(
            role=role, label=label, bounds=region.bounds, state={"user_selected": True},
            clickable=role in {"button", "link", "tab", "checkbox", "radio", "menu"},
            editable=role == "textbox", source=self.name, confidence=1.0,
        )
        observation = PerceptionObservation(
            source=self.name, source_kind="user_guidance", timestamp=datetime.now(timezone.utc),
            screen_dimensions=region.screen_dimensions, screenshot_reference=region.screenshot_reference,
            elements=(element,), confidence=1.0, metadata={"selection": "owner_provided"})
        with self._lock:
            self._latest = observation
        return element

    async def observe(self) -> PerceptionObservation:
        with self._lock:
            current = self._latest
        if current is None:
            raise RuntimeError("No user-selected screen region is available")
        return current
