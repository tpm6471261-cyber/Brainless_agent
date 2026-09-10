"""Normalized, immutable multimodal observations owned by the runtime."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class UIElement:
    role: str
    label: str = ""
    text: str = ""
    bounds: tuple[int, int, int, int] | None = None
    state: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    visible: bool = True
    clickable: bool = False
    editable: bool = False
    source: str = "unknown"
    confidence: float = 0.0
    parent: str | None = None
    children: tuple[str, ...] = ()
    element_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("UI element confidence must be between zero and one")
        if self.bounds and (len(self.bounds) != 4 or self.bounds[2] < 0 or self.bounds[3] < 0):
            raise ValueError("UI element bounds must be x, y, width, height")


@dataclass(frozen=True, slots=True)
class PerceptionObservation:
    source: str
    source_kind: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    active_application: str | None = None
    active_window: str | None = None
    screen_dimensions: tuple[int, int] | None = None
    screenshot_reference: str | None = None
    elements: tuple[UIElement, ...] = ()
    browser_state: dict[str, Any] = field(default_factory=dict)
    filesystem_changes: tuple[dict[str, Any], ...] = ()
    process_changes: tuple[dict[str, Any], ...] = ()
    voice_context: dict[str, Any] = field(default_factory=dict)
    recent_actions: tuple[str, ...] = ()
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    trusted_as_instruction: bool = False

    def __post_init__(self) -> None:
        if self.trusted_as_instruction:
            raise ValueError("Perception is untrusted data and cannot become an instruction")
        if not 0 <= self.confidence <= 1:
            raise ValueError("Observation confidence must be between zero and one")


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    snapshot_id: str
    timestamp: datetime
    active_application: str | None
    active_window: str | None
    screen_dimensions: tuple[int, int] | None
    screenshot_reference: str | None
    visible_elements: tuple[UIElement, ...]
    interactive_elements: tuple[UIElement, ...]
    focused_element: str | None
    browser_state: dict[str, Any]
    filesystem_changes: tuple[dict[str, Any], ...]
    process_changes: tuple[dict[str, Any], ...]
    voice_context: dict[str, Any]
    recent_actions: tuple[str, ...]
    confidence: float
    source_metadata: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class EnvironmentChange:
    kind: str
    detail: dict[str, Any]
    severity: str = "info"
