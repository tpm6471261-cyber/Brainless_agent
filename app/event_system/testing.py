"""Deterministic event source for tests; never enabled by production configuration."""
from __future__ import annotations

from collections import deque

from app.event_system.models import Event


class MockEventGenerator:
    name = "mock"

    def __init__(self, events=()) -> None: self._events = deque(events)

    def emit(self, event_type: str, category: str, **data) -> Event:
        event = Event(event_type, category, self.name, data=data)
        self._events.append(event)
        return event

    async def poll(self) -> tuple[Event, ...]:
        events = tuple(self._events); self._events.clear(); return events
