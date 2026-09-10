"""Least-privilege active multimodal perception orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from time import monotonic

from app.autonomy.events import AutonomousEvent, AutonomousEventBus, EventType
from app.autonomy.world_state import FactKind
from app.perception.change import HumanBlockerDetector, VisualChangeDetector
from app.perception.fusion import PerceptionFusionEngine
from app.perception.models import EnvironmentSnapshot, PerceptionObservation
from app.perception.sources import PerceptionSource


@dataclass(frozen=True, slots=True)
class PerceptionRequest:
    capabilities: frozenset[str]
    reason: str
    mission_id: str | None = None
    agent_id: str | None = None


class MultimodalPerceptionEngine:
    """Select authorized sources, fuse results, and publish structural observations."""

    def __init__(
        self,
        sources: tuple[PerceptionSource, ...],
        events: AutonomousEventBus,
        fusion: PerceptionFusionEngine | None = None,
        world=None,
        capability_authorizer: Callable[[str], set[str]] | None = None,
    ) -> None:
        self.sources, self.events = sources, events
        self.fusion = fusion or PerceptionFusionEngine()
        self.world = world
        self.capability_authorizer = capability_authorizer
        self.on_human_required: Callable[[dict], None] | None = None
        self.changes, self.blockers = VisualChangeDetector(), HumanBlockerDetector()
        self.latest: EnvironmentSnapshot | None = None
        self.observation_count = 0
        self.failed_observations = 0
        self.total_latency_ms = 0.0
        self._lock = asyncio.Lock()

    async def observe(self, request: PerceptionRequest) -> EnvironmentSnapshot:
        if request.agent_id:
            if self.capability_authorizer is None:
                raise PermissionError(
                    "Agent perception requires a runtime capability authorizer"
                )
            missing = request.capabilities - self.capability_authorizer(
                request.agent_id
            )
            if missing:
                raise PermissionError(
                    f"Agent lacks perception capability: {sorted(missing)[0]}"
                )
        async with self._lock:
            return await self._observe_serialized(request)

    async def _observe_serialized(
        self, request: PerceptionRequest
    ) -> EnvironmentSnapshot:
        selected = tuple(
            source
            for source in self.sources
            if source.capabilities & request.capabilities
        )
        if not selected:
            raise PermissionError(
                "No authorized perception source satisfies the request"
            )
        started = monotonic()
        results = await asyncio.gather(
            *(source.observe() for source in selected), return_exceptions=True
        )
        observations = tuple(
            self._scope(item, request.capabilities)
            for item in results
            if isinstance(item, PerceptionObservation)
        )
        failures = tuple(item for item in results if isinstance(item, BaseException))
        self.failed_observations += len(failures)
        for source, result in zip(selected, results):
            if isinstance(result, BaseException):
                await self.events.publish(
                    AutonomousEvent(
                        EventType.PERCEPTION_SOURCE_FAILED,
                        request.mission_id,
                        {"source": source.name, "error": type(result).__name__},
                    )
                )
        if not observations:
            raise RuntimeError("All authorized perception sources failed")

        snapshot = self.fusion.fuse(observations)
        elapsed = (monotonic() - started) * 1000
        self.observation_count += 1
        self.total_latency_ms += elapsed
        if self.world:
            facts = {
                "active_application": snapshot.active_application,
                "active_window": snapshot.active_window,
                "browser_state": snapshot.browser_state,
                "ui_elements": tuple(
                    item.element_id for item in snapshot.visible_elements
                ),
            }
            for key, value in facts.items():
                if value is not None:
                    self.world.record(
                        key,
                        value,
                        kind=FactKind.OBSERVED,
                        source="multimodal_perception",
                        confidence=snapshot.confidence,
                        evidence=snapshot.snapshot_id,
                    )
        await self.events.publish(
            AutonomousEvent(
                EventType.ENVIRONMENT_OBSERVED,
                request.mission_id,
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "sources": [item.source for item in observations],
                    "element_count": len(snapshot.visible_elements),
                    "confidence": snapshot.confidence,
                    "latency_ms": round(elapsed, 3),
                    "reason": request.reason[:200],
                },
            )
        )
        if self.latest:
            for change in self.changes.compare(self.latest, snapshot):
                await self.events.publish(
                    AutonomousEvent(
                        EventType.ENVIRONMENT_DRIFT,
                        request.mission_id,
                        {"kind": change.kind, **change.detail},
                    )
                )
        for blocker in self.blockers.detect(snapshot):
            if self.on_human_required:
                self.on_human_required(blocker.detail)
            await self.events.publish(
                AutonomousEvent(
                    EventType.HUMAN_REQUIRED, request.mission_id, blocker.detail
                )
            )
        self.latest = snapshot
        return snapshot

    def snapshot(self) -> dict:
        current = self.latest
        status = (
            "degraded"
            if current and self.failed_observations
            else "available"
            if current
            else "failed"
            if self.failed_observations
            else "waiting"
        )
        return {
            "status": status,
            "observations": self.observation_count,
            "failed_observations": self.failed_observations,
            "average_latency_ms": self.total_latency_ms / self.observation_count
            if self.observation_count
            else None,
            "snapshot_id": current.snapshot_id if current else None,
            "timestamp": current.timestamp.isoformat() if current else None,
            "active_application": current.active_application if current else None,
            "active_window": current.active_window if current else None,
            "browser": current.browser_state if current else {},
            "screenshot_reference": current.screenshot_reference if current else None,
            "confidence": current.confidence if current else None,
            "elements": [
                {
                    "element_id": item.element_id,
                    "role": item.role,
                    "label": item.label,
                    "text": item.text,
                    "bounds": item.bounds,
                    "source": item.source,
                    "confidence": item.confidence,
                    "clickable": item.clickable,
                    "editable": item.editable,
                }
                for item in current.visible_elements[:200]
            ]
            if current
            else [],
            "sources": list(current.source_metadata) if current else [],
        }

    @staticmethod
    def _scope(
        observation: PerceptionObservation, capabilities: frozenset[str]
    ) -> PerceptionObservation:
        """Remove fields the caller did not request before observations are fused."""
        screen = (
            "screen.read" in capabilities
            or "screen.visual_understanding" in capabilities
        )
        window = "window.read" in capabilities
        browser = "browser.read" in capabilities or "browser.dom.read" in capabilities
        return replace(
            observation,
            active_application=observation.active_application if window else None,
            active_window=observation.active_window if window else None,
            screen_dimensions=observation.screen_dimensions if screen else None,
            screenshot_reference=observation.screenshot_reference if screen else None,
            elements=observation.elements if screen or browser else (),
            browser_state=observation.browser_state if browser else {},
            filesystem_changes=observation.filesystem_changes
            if "filesystem.read" in capabilities
            else (),
            process_changes=observation.process_changes
            if "process.read" in capabilities
            else (),
            voice_context=observation.voice_context
            if "voice.read" in capabilities
            else {},
        )
