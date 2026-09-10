"""Deterministic fusion of runtime observations; later sources cannot inject commands."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.perception.models import EnvironmentSnapshot, PerceptionObservation


class PerceptionFusionEngine:
    def fuse(self, observations: tuple[PerceptionObservation, ...]) -> EnvironmentSnapshot:
        if not observations:
            raise ValueError("At least one perception observation is required")
        ordered = sorted(observations, key=lambda item: item.timestamp)
        latest = ordered[-1]
        def pick(field):
            return next((getattr(item, field) for item in reversed(ordered)
                         if getattr(item, field)), None)
        elements = {item.element_id: item for observation in ordered for item in observation.elements
                    if item.visible}
        filesystem = tuple(change for item in ordered for change in item.filesystem_changes)
        processes = tuple(change for item in ordered for change in item.process_changes)
        browser: dict = {}
        voice: dict = {}
        actions: list[str] = []
        for item in ordered:
            browser.update(item.browser_state)
            voice.update(item.voice_context)
            actions.extend(item.recent_actions)
        confidence = sum(item.confidence for item in ordered) / len(ordered)
        visible = tuple(elements.values())
        return EnvironmentSnapshot(
            str(uuid4()), max(latest.timestamp, datetime.now(timezone.utc)),
            pick("active_application"), pick("active_window"), pick("screen_dimensions"),
            pick("screenshot_reference"), visible,
            tuple(item for item in visible if item.enabled and (item.clickable or item.editable)),
            next((item.element_id for item in visible if item.state.get("focused")), None), browser,
            filesystem, processes, voice, tuple(actions[-20:]), confidence,
            tuple({"source": item.source, "kind": item.source_kind,
                   "timestamp": item.timestamp.isoformat(), "confidence": item.confidence,
                   **item.metadata} for item in ordered),
        )
