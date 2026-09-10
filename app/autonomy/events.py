"""Event-driven wakeups for missions; events are runtime data, never commands."""
from __future__ import annotations
import asyncio
from collections import deque
from queue import Empty, Queue
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4
from threading import Lock
from app.safety.redaction import redact

class EventType(str, Enum):
    USER_MESSAGE="user_message"; SCREEN_CHANGED="screen_changed"; WINDOW_CHANGED="window_changed"; BROWSER_NAVIGATED="browser_navigated"
    FILE_CREATED="file_created"; FILE_MODIFIED="file_modified"; FILE_DELETED="file_deleted"; PROCESS_STOPPED="process_stopped"
    TASK_COMPLETED="task_completed"; TASK_FAILED="task_failed"; AGENT_FAILED="agent_failed"; DEADLINE_APPROACHING="deadline_approaching"
    RESOURCE_AVAILABLE="resource_available"; RESOURCE_CONFLICT="resource_conflict"; APPROVAL_RECEIVED="approval_received"
    TIME_TRIGGERED="time_triggered"; MISSION_TRIGGERED="mission_triggered"; USER_TAKEOVER="user_takeover"
    AGENT_UPDATED="agent_updated"; ACTION_RECORDED="action_recorded"
    VOICE_SESSION="voice_session"; VOICE_PARTIAL="voice_partial"; VOICE_TURN="voice_turn"; VOICE_COMMAND="voice_command"
    ENVIRONMENT_OBSERVED="environment_observed"; ENVIRONMENT_DRIFT="environment_drift"
    UI_DETECTED="ui_detected"; TARGET_RESOLVED="target_resolved"; TARGET_RESOLUTION_FAILED="target_resolution_failed"
    HUMAN_REQUIRED="human_required"
    PERCEPTION_SOURCE_FAILED="perception_source_failed"

@dataclass(frozen=True, slots=True)
class AutonomousEvent:
    type: EventType
    mission_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    sequence: int = 0

class AutonomousEventBus:
    def __init__(self, retention: int = 2_000, persistence=None) -> None:
        self._queue: Queue[AutonomousEvent] = Queue(maxsize=retention)
        self.history: deque[AutonomousEvent] = deque(maxlen=retention)
        self._persistence = persistence
        restored = persistence.recent(retention) if persistence else ()
        self.history.extend(restored)
        self._sequence = restored[-1].sequence if restored else 0
        self._lock = Lock()

    async def publish(self, event: AutonomousEvent) -> None:
        from dataclasses import replace
        with self._lock:
            self._sequence += 1
            recorded = replace(event, detail=redact(event.detail), sequence=self._sequence)
            self.history.append(recorded)
            if self._persistence:
                self._persistence.store_event(recorded)
        # Backpressure is explicit: important runtime events are not silently lost.
        await asyncio.to_thread(self._queue.put, recorded)

    def replay(self, since: int = 0, limit: int = 200) -> tuple[AutonomousEvent, ...]:
        return tuple(item for item in self.history if item.sequence > since)[:max(0, min(limit, 1_000))]

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()
    async def next(self, timeout: float | None = None) -> AutonomousEvent | None:
        try:
            if timeout == 0:
                return self._queue.get_nowait()
            return await asyncio.to_thread(self._queue.get, True, timeout)
        except Empty: return None
