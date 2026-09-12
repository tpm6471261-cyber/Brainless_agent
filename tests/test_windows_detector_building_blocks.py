import asyncio
import time

from app.agents.manager import AgentManager
from app.event_system import (ActionRegistry, ActionSpec, AgentActionExecutor, AgentBlueprint,
    AgentEventDispatcher, AudioDetector, DeviceDetector, Event, EventBus, EventFilter,
    EventSubscription, KeyboardDetector, KeyboardPrivacyFilter, MouseDetector,
    NotificationDetector, RiskLevel, SessionDetector, create_event_platform,
    EventSystemConfig, FilesystemDetector, WindowDetector, create_windows_detectors)


def test_keyboard_transitions_hotkey_and_private_printable_keys():
    async def scenario():
        states = iter(({"CTRL": True, "C": True}, {"CTRL": False, "C": False}))
        detector = KeyboardDetector(lambda: next(states), privacy=KeyboardPrivacyFilter())
        first = await detector.poll()
        assert {event.event_type for event in first} == {"ON_KEY_DOWN", "ON_KEY_PRESS", "ON_HOTKEY", "ON_MODIFIER_CHANGED"}
        assert any(event.data.get("key") == "[REDACTED]" for event in first)
        second = await detector.poll()
        assert {event.event_type for event in second} == {"ON_KEY_UP", "ON_MODIFIER_CHANGED"}
    asyncio.run(scenario())


def test_keyboard_privacy_always_redacts_sensitive_windows():
    privacy = KeyboardPrivacyFilter(expose_printable_keys=True)
    assert privacy.protect("A", process="browser.exe", window="Password entry") == "[REDACTED]"
    assert privacy.protect("A", process="browser.exe", window="Document") == "A"


def test_mouse_derives_button_drag_target_and_double_click_events():
    async def scenario():
        now = [1.0]
        states = iter((
            {"x": 1, "y": 1, "buttons": {}, "target_window": "one"},
            {"x": 1, "y": 1, "buttons": {"left": True}, "target_window": "one"},
            {"x": 5, "y": 4, "buttons": {"left": True}, "target_window": "two"},
            {"x": 5, "y": 4, "buttons": {}, "target_window": "two"},
            {"x": 5, "y": 4, "buttons": {"left": True}, "target_window": "two"},
        ))
        detector = MouseDetector(lambda: next(states), clock=lambda: now[0])
        assert (await detector.poll())[0].event_type == "ON_MOUSE_POSITION_CHANGED"
        assert "ON_MOUSE_LEFT_DOWN" in {event.event_type for event in await detector.poll()}
        kinds = {event.event_type for event in await detector.poll()}
        assert {"ON_MOUSE_MOVE", "ON_MOUSE_ENTER", "ON_MOUSE_LEAVE", "ON_MOUSE_DRAG_START", "ON_MOUSE_DRAG"}.issubset(kinds)
        assert "ON_MOUSE_DRAG_END" in {event.event_type for event in await detector.poll()}
        now[0] = 1.2
        assert "ON_MOUSE_DOUBLE_CLICK" in {event.event_type for event in await detector.poll()}
    asyncio.run(scenario())


def test_device_audio_session_and_notification_adapters_emit_real_diffs():
    async def scenario():
        device = DeviceDetector(lambda: {"usb-1": {"device_class": "USB", "name": "Drive", "status": "OK"}})
        assert {e.event_type for e in await device.poll()} == {"ON_DEVICE_CONNECTED", "ON_USB_CONNECTED"}
        device.reader = lambda: {}
        assert {e.event_type for e in await device.poll()} == {"ON_DEVICE_DISCONNECTED", "ON_USB_DISCONNECTED"}

        audio = AudioDetector(lambda: {"speaker": {"device_class": "AudioEndpoint", "name": "Speakers"}})
        assert {e.event_type for e in await audio.poll()} == {"ON_AUDIO_DEVICE_CONNECTED", "ON_AUDIO_DEVICE_CHANGED"}

        session = SessionDetector(lambda: {"1": {"session_id": "1", "logon_type": 2}})
        assert (await session.poll())[0].event_type == "ON_USER_LOGIN"
        session.reader = lambda: {}
        assert (await session.poll())[0].event_type == "ON_USER_LOGOUT"

        notifications = NotificationDetector(lambda: {"7": {"title": "Permission required", "application": "App"}})
        event = (await notifications.poll())[0]
        assert event.event_type == "ON_PERMISSION_DIALOG" and "content" not in event.data
    asyncio.run(scenario())


def test_paused_bus_retains_pending_events_until_resume():
    async def scenario():
        received = []
        bus = EventBus()
        bus.subscribe(EventSubscription("all", EventFilter(event_types=frozenset({"*"}))), received.append)
        bus.pause()
        event = Event("ON_TIMER", "scheduler", "test")
        await bus.publish(event)
        assert not received and bus.history.replay() == (event,)
        await bus.resume()
        assert received == [event]
    asyncio.run(scenario())


def test_dispatch_rate_limit_and_agent_risk_boundary():
    async def scenario():
        manager = AgentManager(); parent = manager.create_root("root", "root", "test", {"system.observe", "system.control"})
        child = AgentBlueprint("safe", "safe", permissions=frozenset({"system.observe", "system.control"}),
            subscriptions=frozenset({"*"}), resource_limits={"max_event_rate": 1}, risk_policy="low").create(manager, parent.agent_id)
        delivered = []
        from app.event_system import AgentResourceLimiter
        dispatcher = AgentEventDispatcher(manager, lambda agent, event: delivered.append(event), AgentResourceLimiter())
        event = Event("ON_TIMER", "scheduler", "test", permissions_required=frozenset({"system.observe"}))
        await dispatcher.dispatch(event); await dispatcher.dispatch(Event("ON_INTERVAL", "scheduler", "test", permissions_required=frozenset({"system.observe"})))
        assert len(delivered) == 1
        registry = ActionRegistry(confirm=lambda _: True)
        registry.register(ActionSpec("POWER", "power", "power", frozenset({"system.control"}), RiskLevel.HIGH, frozenset(), "none", lambda _: True))
        result = await AgentActionExecutor(registry).execute(child, "POWER")
        assert not result.success and "risk policy" in result.message
    asyncio.run(scenario())


def test_platform_factory_keeps_sensitive_detectors_disabled_by_default():
    platform = create_event_platform(EventSystemConfig(enabled=False))
    assert platform.manager.detectors == []
    assert create_windows_detectors(keyboard=False, mouse=False, devices=False, audio=False, sessions=False) == ()


def test_sync_action_executor_is_timeout_guarded_without_blocking_loop():
    async def scenario():
        from app.event_system import ActionStatus
        registry = ActionRegistry()
        registry.register(ActionSpec("SLOW", "slow", "test", frozenset(), RiskLevel.LOW,
            frozenset(), "none", lambda _: time.sleep(.05), timeout=.001))
        assert (await registry.execute("SLOW", {}, set())).status is ActionStatus.TIMEOUT
    asyncio.run(scenario())


def test_filesystem_rename_and_specific_window_transitions(tmp_path):
    async def scenario():
        filesystem = FilesystemDetector((tmp_path,)); await filesystem.poll()
        original = tmp_path / "old.txt"; original.write_text("data"); await filesystem.poll()
        renamed = tmp_path / "new.txt"; original.rename(renamed)
        event = (await filesystem.poll())[0]
        assert event.event_type == "ON_FILE_RENAMED" and event.data["previous_path"].endswith("old.txt")
        states = iter(({"1": {"title": "A", "position": {"x": 0}, "size": {"width": 1}, "state": "normal"}},
                       {"1": {"title": "B", "position": {"x": 2}, "size": {"width": 2}, "state": "maximized"}}, {}))
        windows = WindowDetector(lambda: next(states))
        assert {e.event_type for e in await windows.poll()} == {"ON_WINDOW_CREATED", "ON_WINDOW_OPENED"}
        changed = {e.event_type for e in await windows.poll()}
        assert {"ON_WINDOW_TITLE_CHANGED", "ON_WINDOW_MOVED", "ON_WINDOW_RESIZED", "ON_WINDOW_MAXIMIZED", "ON_WINDOW_STATE_CHANGED"}.issubset(changed)
        assert {e.event_type for e in await windows.poll()} == {"ON_WINDOW_DESTROYED", "ON_WINDOW_CLOSED"}
    asyncio.run(scenario())
