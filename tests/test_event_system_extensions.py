import asyncio
from datetime import datetime, timedelta, timezone

from app.agents.manager import AgentManager
from app.event_system import (ActionRegistry, ActionSpec, ActionStatus, AgentBlueprint,
    Event, EventBus, EventManager, EventSubscription, EventFilter, NetworkDetector,
    PowerDetector, RiskLevel, SchedulerDetector, create_event_agent,
    discover_agent_actions, permission_for_event)


def test_replay_routes_retained_event_without_duplicating_history():
    async def scenario():
        bus=EventBus();event=Event("ON_TIMER","scheduler","test")
        await bus.publish(event);received=[]
        bus.subscribe(EventSubscription("timers",EventFilter(event_types=frozenset({"ON_TIMER"}))),received.append)
        assert await bus.replay(event_type="ON_TIMER")==1
        assert received==[event] and bus.history.replay()==(event,)
    asyncio.run(scenario())


def test_optional_detector_failure_does_not_stop_healthy_detectors():
    class Broken:
        name="optional"
        async def poll(self):raise ImportError("native adapter missing")
    class Healthy:
        name="healthy"
        async def poll(self):return (Event("ON_TIMER","scheduler","healthy"),)
    async def scenario():
        manager=EventManager(EventBus(),(Broken(),Healthy()))
        assert len(await manager.poll_once())==1
        assert manager.unavailable=={"optional":"native adapter missing"}
    asyncio.run(scenario())


def test_network_power_and_scheduler_use_injected_real_adapter_boundaries():
    async def scenario():
        network=NetworkDetector(lambda:{"ethernet":{"interface":"Ethernet","ip":"192.0.2.1"}})
        assert (await network.poll())[0].event_type=="ON_NETWORK_CONNECTED"
        network.reader=lambda:{}
        assert (await network.poll())[0].event_type=="ON_NETWORK_DISCONNECTED"
        states=iter(({"battery_percentage":20,"charging":False,"power_source":"battery"},
                     {"battery_percentage":15,"charging":True,"power_source":"ac"}))
        power=PowerDetector(lambda:next(states))
        assert (await power.poll())[0].event_type=="ON_AC_DISCONNECTED"
        assert {e.event_type for e in await power.poll()}=={"ON_AC_CONNECTED","ON_BATTERY_LEVEL_CHANGED","ON_BATTERY_LOW"}
        now=datetime.now(timezone.utc);scheduler=SchedulerDetector(lambda:now)
        scheduler.schedule("once",now-timedelta(seconds=1),data={"job":"safe"})
        assert (await scheduler.poll())[0].data["job"]=="safe" and await scheduler.poll()==()
    asyncio.run(scenario())


def test_functional_agent_factory_and_action_discovery_are_permission_scoped():
    manager=AgentManager();root=manager.create_root("root","root","test",{"screen.capture"})
    agent=create_event_agent(manager,root.agent_id,name="vision",purpose="inspect",permissions={"screen.capture"},subscriptions={"ON_SCREEN_CHANGED"})
    registry=ActionRegistry();registry.register(ActionSpec("SHOT","shot","screen",frozenset({"screen.capture"}),RiskLevel.MEDIUM,frozenset(),"path",lambda _:"x"))
    registry.register(ActionSpec("DELETE","delete","filesystem",frozenset({"filesystem.delete"}),RiskLevel.HIGH,frozenset(),"bool",lambda _:True))
    assert [x["action_name"] for x in discover_agent_actions(registry,agent)]==["SHOT"]
    assert permission_for_event("screen")=="screen.observe"


def test_circuit_breaker_opens_after_repeated_integration_failures():
    async def scenario():
        registry=ActionRegistry();registry.register(ActionSpec("FAIL","fail","test",frozenset(),RiskLevel.LOW,frozenset(),"none",lambda _:1/0))
        for _ in range(3):assert (await registry.execute("FAIL",{},set())).status is ActionStatus.FAILED
        assert (await registry.execute("FAIL",{},set())).status is ActionStatus.NOT_SUPPORTED
        registry.resume();assert (await registry.execute("FAIL",{},set())).status is ActionStatus.FAILED
    asyncio.run(scenario())
