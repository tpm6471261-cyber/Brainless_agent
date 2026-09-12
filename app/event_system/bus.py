"""Priority event bus with filtered subscriptions and bounded replay history."""
from __future__ import annotations
import asyncio
import hashlib
import json
from collections import deque
from collections.abc import Awaitable, Callable
from time import monotonic
from app.event_system.models import Event, EventSubscription

EventHandler = Callable[[Event], Awaitable[None] | None]

class EventHistory:
    def __init__(self, limit: int = 5000) -> None: self._events=deque(maxlen=max(1, limit))
    def append(self, event: Event) -> None: self._events.append(event)
    def replay(self, *, event_type: str | None=None, since=None) -> tuple[Event, ...]:
        return tuple(e for e in self._events if (not event_type or e.event_type == event_type) and (not since or e.timestamp >= since))
    def clear(self) -> None: self._events.clear()

class EventBus:
    def __init__(self, history: EventHistory | None=None, dedupe_seconds: float=.25) -> None:
        self.history=history or EventHistory(); self.dedupe_seconds=dedupe_seconds
        self._subscriptions: dict[str, tuple[EventSubscription, EventHandler]]={}
        self._last_delivery: dict[tuple[str,str], float]={}; self._dedupe: dict[str,float]={}
        self.paused=False; self._queue: asyncio.PriorityQueue=asyncio.PriorityQueue(); self._sequence=0
    def subscribe(self, subscription: EventSubscription, handler: EventHandler) -> None:
        self._subscriptions[subscription.subscriber_id]=(subscription,handler)
    def unsubscribe(self, subscriber_id: str) -> None: self._subscriptions.pop(subscriber_id,None)
    async def publish(self, event: Event) -> bool:
        fingerprint=hashlib.sha256(json.dumps([event.event_type,event.source,event.process,event.window,event.data],sort_keys=True,default=str).encode()).hexdigest()
        now=monotonic(); last=self._dedupe.get(fingerprint)
        if last is not None and now-last < self.dedupe_seconds: return False
        self._dedupe[fingerprint]=now; self.history.append(event)
        if self.paused: return True
        self._sequence += 1; await self._queue.put((-event.priority,self._sequence,event)); await self.route_pending(); return True
    async def route_pending(self) -> None:
        while not self._queue.empty():
            _,_,event=await self._queue.get(); now=monotonic()
            for key,(subscription,handler) in tuple(self._subscriptions.items()):
                if not subscription.event_filter.matches(event): continue
                previous=self._last_delivery.get((key,event.event_type),-1e9)
                interval=max(subscription.debounce_seconds,subscription.throttle_seconds)
                if now-previous < interval: continue
                result=handler(event)
                if hasattr(result,"__await__"): await result
                self._last_delivery[(key,event.event_type)]=now

class EventRouter:
    def __init__(self,bus: EventBus) -> None: self.bus=bus
    def route(self,subscription: EventSubscription,handler: EventHandler) -> None: self.bus.subscribe(subscription,handler)

class EventDetector:
    name="detector"
    async def poll(self) -> tuple[Event,...]: raise NotImplementedError

class EventManager:
    def __init__(self,bus: EventBus,detectors=()) -> None: self.bus,self.detectors=bus,list(detectors); self.running=False
    async def poll_once(self) -> tuple[Event,...]:
        emitted=[]
        for detector in self.detectors:
            try: events=await detector.poll()
            except (ImportError,OSError,RuntimeError): continue
            for event in events: await self.bus.publish(event); emitted.append(event)
        return tuple(emitted)
