import asyncio
from app.event_system import (ActionRegistry,ActionSpec,ActionStatus,ConditionEngine,Event,EventBus,
    EventFilter,EventSubscription,FilesystemDetector,RiskLevel,WindowsCapabilityReport)
from app.event_system import AgentEventDispatcher
from app.event_system import AutoWindow
from app.event_system import ClipboardDetector,DisplayDetector,MousePositionDetector,ProcessDetector
from app.event_system import KeyboardStateDetector,NetworkDetector,PowerDetector,SchedulerDetector,WindowDetector
from app.agents.manager import AgentManager
from datetime import datetime

def test_bus_filters_deduplicates_routes_and_replays():
    async def scenario():
        received=[];bus=EventBus(dedupe_seconds=10)
        bus.subscribe(EventSubscription("pdf",EventFilter(event_types=frozenset({"ON_FILE_CREATED"}),
            categories=frozenset({"filesystem"}),conditions={"field":"extension","operator":"equals","value":".pdf"})),received.append)
        event=Event("ON_FILE_CREATED","filesystem","test",data={"extension":".pdf"},priority=10)
        assert await bus.publish(event);assert not await bus.publish(Event("ON_FILE_CREATED","filesystem","test",data={"extension":".pdf"}))
        assert received==[event] and bus.history.replay(event_type="ON_FILE_CREATED")== (event,)
        bus.unsubscribe("pdf")
    asyncio.run(scenario())

def test_conditions_support_nested_logic_and_changes():
    data={"path":"C:/Downloads/a.pdf","extension":".pdf","size":5,"previous_size":2}
    assert ConditionEngine.matches(data,{"AND":[{"field":"extension","value":".pdf"},{"field":"size","operator":"greater_than","value":2}]})
    assert ConditionEngine.matches(data,{"field":"size","operator":"changed"})

def test_keyboard_detector_is_opt_in_and_never_captures_text():
    async def scenario():
        states=iter(({"CTRL","C"},set()))
        detector=KeyboardStateDetector(lambda:next(states),enabled=True,hotkeys=(("CTRL","C"),))
        first=await detector.poll()
        assert {event.event_type for event in first}=={"ON_KEY_DOWN","ON_MODIFIER_CHANGED","ON_HOTKEY"}
        assert all("text" not in event.data for event in first)
        assert {event.event_type for event in await detector.poll()}=={"ON_KEY_UP","ON_MODIFIER_CHANGED"}
        assert await KeyboardStateDetector(lambda:{"A"}).poll()==()
    asyncio.run(scenario())

def test_window_power_network_and_scheduler_snapshot_diffs():
    async def scenario():
        windows=iter((({1:{"window_handle":1,"title":"A","position":(0,0),"size":(10,10),"visible":True,"state":"normal"}},1),
                      ({1:{"window_handle":1,"title":"B","position":(2,0),"size":(10,10),"visible":True,"state":"normal"}},1)))
        detector=WindowDetector(lambda:next(windows));assert {e.event_type for e in await detector.poll()}=={"ON_WINDOW_CREATED","ON_WINDOW_ACTIVATED"}
        assert {e.event_type for e in await detector.poll()}=={"ON_WINDOW_TITLE_CHANGED","ON_WINDOW_MOVED"}
        power=PowerDetector(lambda:{"ac_connected":False,"battery_percent":4,"charging":False})
        assert {e.event_type for e in await power.poll()}=={"ON_BATTERY_LEVEL_CHANGED","ON_BATTERY_CRITICAL"}
        network_values=iter(([],["10.0.0.1"]));network=NetworkDetector(lambda:next(network_values));await network.poll()
        assert {e.event_type for e in await network.poll()}=={"ON_NETWORK_CONNECTED","ON_IP_CHANGED"}
        times=iter((datetime(2026,1,1,23,59),datetime(2026,1,2,0,0)));scheduler=SchedulerDetector(1,lambda:next(times));await scheduler.poll()
        assert {e.event_type for e in await scheduler.poll()}=={"ON_INTERVAL","ON_MINUTE","ON_HOUR","ON_DATE_CHANGED"}
    asyncio.run(scenario())

def test_filesystem_detector_emits_real_create_modify_delete(tmp_path):
    async def scenario():
        detector=FilesystemDetector((tmp_path,));await detector.poll()
        path=tmp_path/"a.pdf";path.write_text("a");assert (await detector.poll())[0].event_type=="ON_FILE_CREATED"
        path.write_text("longer");assert (await detector.poll())[0].event_type=="ON_FILE_SIZE_CHANGED"
        path.unlink();assert (await detector.poll())[0].event_type=="ON_FILE_DELETED"
    asyncio.run(scenario())

def test_action_registry_permissions_risk_dry_run_retry_and_stop():
    async def scenario():
        calls=[]
        async def execute(args):calls.append(args);return "ok"
        spec=ActionSpec("MOVE_FILE","move","filesystem",frozenset({"filesystem.write"}),RiskLevel.MEDIUM,frozenset({"path"}),"string",execute)
        registry=ActionRegistry(dry_run=True);registry.register(spec)
        assert (await registry.execute("MOVE_FILE",{"path":"x"},{"filesystem.write"})).status is ActionStatus.DENIED
        registry.dry_run=False;assert (await registry.execute("MOVE_FILE",{"path":"x"},set())).status is ActionStatus.DENIED
        assert (await registry.execute("MOVE_FILE",{"path":"x"},{"filesystem.write"})).success
        registry.emergency_stop();assert (await registry.execute("MOVE_FILE",{"path":"x"},{"filesystem.write"})).status is ActionStatus.CANCELLED
    asyncio.run(scenario())

def test_capability_report_is_explicit_not_fabricated():
    report=WindowsCapabilityReport.detect();assert report["Filesystem"]=="AVAILABLE" and report["Browser"]=="PARTIAL"

def test_agents_receive_only_subscribed_events_with_held_observation_permission():
    async def scenario():
        manager=AgentManager();root=manager.create_root("root","root","events",{"filesystem.read"})
        child=manager.create_agent(root.agent_id,"files","worker","pdf",permissions={"filesystem.read"})
        manager.set_event_subscriptions(root.agent_id,child.agent_id,{"ON_FILE_CREATED"})
        received=[];dispatcher=AgentEventDispatcher(manager,lambda agent,event:received.append((agent.agent_id,event.event_type)))
        allowed=Event("ON_FILE_CREATED","filesystem","watcher",permissions_required=frozenset({"filesystem.read"}))
        denied=Event("ON_KEY_DOWN","keyboard","hook",permissions_required=frozenset({"keyboard.observe"}))
        assert await dispatcher.dispatch(allowed)==(child.agent_id,)
        assert await dispatcher.dispatch(denied)==() and received==[(child.agent_id,"ON_FILE_CREATED")]
    asyncio.run(scenario())

def test_autowindow_one_call_actions_data_variables_and_stop(tmp_path):
    pc=AutoWindow(permissions={"filesystem.write"},watch_paths=(tmp_path,),confirm=lambda _:True)
    target=tmp_path/"created.txt"
    result=pc.call_action_sync("CREATE_FILE",path=str(target),content="real")
    assert result.success and target.read_text()=="real"
    pc.set_variable("answer",42);assert pc.get_variable("answer")==42
    assert pc.get_data("DISK_USAGE",path=tmp_path)["total"]>0
    pc.emergency_stop()
    assert pc.call_action_sync("CREATE_FOLDER",path=str(tmp_path/"blocked")).status is ActionStatus.CANCELLED
    pc.resume_agent_system()
    assert pc.call_action_sync("CREATE_FOLDER",path=str(tmp_path/"allowed")).success

def test_privacy_safe_clipboard_mouse_display_and_process_detectors():
    async def scenario():
        clipboard=ClipboardDetector(lambda:"password=secret",enabled=True)
        event=(await clipboard.poll())[0];assert event.data=={"content_type":"text","length":15}
        assert "secret" not in str(event.data) and await clipboard.poll()==()
        mouse=MousePositionDetector(lambda:(10,20));assert (await mouse.poll())[0].data["x"]==10
        display=DisplayDetector(lambda:(1920,1080));assert (await display.poll())[0].event_type=="ON_DISPLAY_CONFIGURATION_CHANGED"
        states=iter(({1:"one.exe"},{2:"two.exe"}));processes=ProcessDetector(lambda:next(states))
        assert (await processes.poll())[0].event_type=="ON_PROCESS_STARTED"
        assert {e.event_type for e in await processes.poll()}=={"ON_PROCESS_STARTED","ON_PROCESS_STOPPED"}
    asyncio.run(scenario())
