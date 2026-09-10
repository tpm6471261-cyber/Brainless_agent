"""Persistent, event-driven mission supervisor.

The operator owns lifecycle and state only. A supplied trusted mission runner must use
existing TaskEngine/ActionRuntime paths; reasoning providers never receive this object.
"""
from __future__ import annotations
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from app.autonomy.events import AutonomousEvent, AutonomousEventBus, EventType
from app.autonomy.mission import Mission, MissionStatus, MissionStore
from app.autonomy.perception_service import PerceptionService
from app.safety.redaction import redact

class AutonomyMode(str, Enum):
    OBSERVE_ONLY="observe_only"; ASSISTED="assisted"; AUTONOMOUS="autonomous"; SUPERVISED="supervised"; WATCH="watch"; TAKEOVER="takeover"; PAUSED="paused"

class MissionRunner(Protocol):
    async def __call__(self, mission: Mission) -> MissionStatus: ...

class UserTakeoverManager:
    def __init__(self) -> None: self.mode = AutonomyMode.AUTONOMOUS
    def begin(self) -> None: self.mode = AutonomyMode.TAKEOVER
    def resume(self) -> None: self.mode = AutonomyMode.AUTONOMOUS
    @property
    def actions_allowed(self) -> bool: return self.mode is AutonomyMode.AUTONOMOUS

class BlockerDetector:
    def classify(self, event: AutonomousEvent) -> MissionStatus | None:
        if event.type is EventType.USER_TAKEOVER: return MissionStatus.AWAITING_USER
        if event.type is EventType.RESOURCE_CONFLICT: return MissionStatus.WAITING
        if event.type is EventType.AGENT_FAILED: return MissionStatus.RECOVERING
        if event.type is EventType.TASK_FAILED: return MissionStatus.BLOCKED
        return None

class AutonomousOperator:
    """Runs one bounded mission turn at a time, sleeping on its event queue when idle."""
    def __init__(self, store: MissionStore, perception: PerceptionService, events: AutonomousEventBus,
                 runner: MissionRunner, *, takeover: UserTakeoverManager | None = None,
                 blockers: BlockerDetector | None = None,
                 event_handlers: tuple[Callable[[AutonomousEvent], Awaitable[object]], ...] = ()) -> None:
        self.store, self.perception, self.events, self.runner = store, perception, events, runner
        self.takeover, self.blockers = takeover or UserTakeoverManager(), blockers or BlockerDetector()
        self.event_handlers = event_handlers

    async def create(self, mission: Mission) -> Mission:
        mission.status = MissionStatus.PLANNING; mission.touch(); self.store.save(mission)
        await self.events.publish(AutonomousEvent(EventType.MISSION_TRIGGERED, mission.mission_id))
        return mission

    async def run_once(self, mission_id: str) -> Mission:
        mission = self.store.load(mission_id)
        if mission is None: raise KeyError(f"Unknown mission: {mission_id}")
        if mission.status in {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED}: return mission
        # PAUSED is an explicit operator decision. Merely receiving an unrelated
        # event must never make the mission runnable again.
        if mission.status is MissionStatus.PAUSED: return mission
        snapshot = await self.perception.observe(mission_id)
        mission.current_state = snapshot.values(); mission.checkpoint["world_version"] = snapshot.version
        if self.takeover.mode is AutonomyMode.TAKEOVER:
            mission.status = MissionStatus.AWAITING_USER; mission.touch(); self.store.save(mission); return mission
        if self.takeover.mode in {AutonomyMode.OBSERVE_ONLY, AutonomyMode.ASSISTED, AutonomyMode.WATCH, AutonomyMode.PAUSED}:
            mission.status = MissionStatus.WAITING; mission.touch(); self.store.save(mission); return mission
        mission.status = MissionStatus.RUNNING; mission.touch(); self.store.save(mission)
        try:
            mission.status = await self.runner(mission)
        except Exception as error:
            mission.status = MissionStatus.RECOVERING
            safe_error = redact(str(error))
            mission.checkpoint["last_error"] = safe_error
            await self.events.publish(AutonomousEvent(EventType.AGENT_FAILED, mission_id, {"error": safe_error}))
        mission.refresh_progress(); mission.touch(); self.store.save(mission)
        return mission

    async def process_event(self, event: AutonomousEvent) -> Mission | None:
        for handler in self.event_handlers:
            await handler(event)
        if event.type is EventType.USER_TAKEOVER: self.takeover.begin()
        if event.mission_id is None: return None
        mission = self.store.load(event.mission_id)
        if mission is None: return None
        if status := self.blockers.classify(event): mission.status = status
        mission.checkpoint["last_event"] = event.type.value; mission.touch(); self.store.save(mission)
        return mission

    async def run_background(self, *, stop: Callable[[], bool], idle_seconds: float = 30.0) -> None:
        """Event-driven loop: no model calls or busy polling while idle."""
        while not stop():
            for mission in sorted(self.store.active(), key=lambda item: (-item.priority, item.created_at)):
                await self.run_once(mission.mission_id)
            event = await self.events.next(idle_seconds)
            if event: await self.process_event(event)

    async def resume_active(self) -> tuple[Mission, ...]:
        """Restart recovery always observes before resuming; no stored action is replayed."""
        restored = []
        for mission in self.store.active():
            mission.status = MissionStatus.WAITING
            self.store.save(mission)
            restored.append(await self.run_once(mission.mission_id))
        return tuple(restored)
