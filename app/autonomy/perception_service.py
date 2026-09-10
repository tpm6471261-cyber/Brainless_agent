"""Cheap deterministic observation first, with event emission only on meaningful drift."""
from __future__ import annotations
from app.autonomy.events import AutonomousEvent, AutonomousEventBus, EventType
from app.autonomy.world_state import WorldStateManager

class PerceptionService:
    def __init__(self, controller, world: WorldStateManager, events: AutonomousEventBus) -> None:
        self.controller, self.world, self.events, self._last = controller, world, events, None
    async def observe(self, mission_id: str | None = None, *, source: str = "perception"):
        state = await self.controller.observe(); snapshot = self.world.capture(state, source=source)
        if self._last is not None:
            changed = self.world.diff(self._last, snapshot)
            if changed:
                event = EventType.BROWSER_NAVIGATED if "browser_url" in changed else EventType.WINDOW_CHANGED if "active_window" in changed else EventType.SCREEN_CHANGED
                await self.events.publish(AutonomousEvent(event, mission_id, {"changed": sorted(changed)}))
        self._last = snapshot
        return snapshot
