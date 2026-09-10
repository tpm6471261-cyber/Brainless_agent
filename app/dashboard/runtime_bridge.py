"""Bridges existing append-only runtime records into dashboard events."""
from __future__ import annotations

from app.autonomy.events import AutonomousEvent, AutonomousEventBus, EventType


class RuntimeEventBridge:
    """Incrementally publishes real agent/action records without duplicating authority."""
    def __init__(self, agents, actions, events: AutonomousEventBus) -> None:
        self.agents, self.actions, self.events = agents, actions, events
        self._agent_offset = 0
        self._action_offset = 0

    async def pump_once(self) -> int:
        published = 0
        for item in self.agents.events[self._agent_offset:]:
            event_type = EventType.AGENT_FAILED if item.type.value == "error" else (
                EventType.TASK_COMPLETED if item.type.value == "result" else EventType.AGENT_UPDATED)
            await self.events.publish(AutonomousEvent(event_type, detail={
                "agent_id": item.agent_id, "task_id": item.task_id, "status": item.type.value,
                "message": item.detail, "parent_agent_id": item.parent_agent_id,
            }))
            published += 1
        self._agent_offset = len(self.agents.events)
        for item in self.actions.audit[self._action_offset:]:
            await self.events.publish(AutonomousEvent(EventType.ACTION_RECORDED, detail={
                "agent_id": item.agent_id, "task_id": item.task_id, "action_id": item.action_id,
                "tool": item.tool, "status": "failed" if item.error else "completed",
                "duration_ms": item.duration_ms, "severity": "error" if item.error else "info",
            }))
            published += 1
        self._action_offset = len(self.actions.audit)
        return published
