"""Persisted deterministic triggers and cheap filesystem/process watcher adapters."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Callable, Any
from uuid import uuid4
from app.autonomy.events import AutonomousEvent, AutonomousEventBus, EventType

class TriggerKind(str, Enum): TIME="time"; EVENT="event"; CONDITION="condition"; MISSION="mission"
@dataclass(slots=True)
class Trigger:
    mission_id: str; kind: TriggerKind; value: str; enabled: bool = True; trigger_id: str = field(default_factory=lambda: str(uuid4())); last_fired: str | None = None
class TriggerStore:
    def __init__(self, path: Path) -> None: self.path = path
    def save(self, trigger: Trigger) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True); data=self._read(); data[trigger.trigger_id]=asdict(trigger); data[trigger.trigger_id]["kind"]=trigger.kind.value
        tmp=self.path.with_suffix(".tmp"); tmp.write_text(json.dumps(data,sort_keys=True),encoding="utf-8"); tmp.replace(self.path)
    def all(self) -> tuple[Trigger,...]: return tuple(Trigger(**(item | {"kind": TriggerKind(item["kind"])})) for item in self._read().values())
    def _read(self): return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
class TriggerEngine:
    def __init__(self, store: TriggerStore, events: AutonomousEventBus, *, policy: Callable[[Trigger], bool] | None = None, conditions: dict[str, Callable[[], bool]] | None = None) -> None:
        self.store,self.events,self.policy,self.conditions=store,events,policy or (lambda _: True),conditions or {}

    async def _fire(self, trigger: Trigger, event_type: EventType, *, disable: bool = False) -> Trigger:
        if not self.policy(trigger):
            return trigger
        trigger.last_fired=datetime.now(timezone.utc).isoformat(); trigger.enabled=not disable; self.store.save(trigger)
        await self.events.publish(AutonomousEvent(event_type,trigger.mission_id,{"trigger_id":trigger.trigger_id}))
        return trigger
    async def tick(self, now: datetime | None = None) -> tuple[Trigger,...]:
        now=now or datetime.now(timezone.utc); fired=[]
        for trigger in self.store.all():
            if trigger.enabled and trigger.kind is TriggerKind.TIME and now >= datetime.fromisoformat(trigger.value):
                fired.append(await self._fire(trigger, EventType.TIME_TRIGGERED, disable=True))
            elif trigger.enabled and trigger.kind is TriggerKind.CONDITION and self.conditions.get(trigger.value, lambda: False)():
                fired.append(await self._fire(trigger, EventType.MISSION_TRIGGERED))
        return tuple(fired)
    async def handle(self,event: AutonomousEvent)->tuple[Trigger,...]:
        fired=[]
        for trigger in self.store.all():
            matches_event = trigger.kind is TriggerKind.EVENT and trigger.value == event.type.value
            matches_mission = trigger.kind is TriggerKind.MISSION and event.type is EventType.TASK_COMPLETED and trigger.value == str(event.mission_id)
            if trigger.enabled and (matches_event or matches_mission):
                fired.append(await self._fire(trigger, EventType.MISSION_TRIGGERED))
        return tuple(fired)
class FilesystemWatcher:
    def __init__(self,path:Path):
        self.path=path
        self._known={item.name:item.stat().st_mtime_ns for item in path.iterdir()} if path.exists() else {}
    def poll(self)->tuple[EventType,...]:
        current={item.name:item.stat().st_mtime_ns for item in self.path.iterdir()} if self.path.exists() else {}; events=[]
        events += [EventType.FILE_CREATED for key in current.keys()-self._known.keys()]; events += [EventType.FILE_DELETED for key in self._known.keys()-current.keys()]
        events += [EventType.FILE_MODIFIED for key in current.keys() & self._known.keys() if current[key]!=self._known[key]]; self._known=current; return tuple(events)
class ProcessWatcher:
    def __init__(self, snapshot: Callable[[], set[str]]): self.snapshot,self._known=snapshot,set()
    def poll(self)->tuple[EventType,...]:
        current=self.snapshot(); events=tuple(EventType.PROCESS_STOPPED for _ in self._known-current); self._known=current; return events
