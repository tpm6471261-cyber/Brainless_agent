import asyncio
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from app.agents.manager import AgentManager
from app.autonomy.controllers import FilesystemComputerController
from app.autonomy.events import AutonomousEvent, AutonomousEventBus, EventType
from app.autonomy.executor import ActionRuntime
from app.autonomy.mission import Mission, MissionStatus, MissionStore
from app.autonomy.operator import AutonomousOperator
from app.autonomy.perception_service import PerceptionService
from app.dashboard import DashboardRuntime, DashboardServer, DashboardService, RuntimeCommandGateway

TOKEN = "test-dashboard-token-123"


def dashboard(tmp_path):
    manager = AgentManager()
    manager.create_root("Operator", "root", "supervise", set())
    controller = FilesystemComputerController(tmp_path)
    actions = ActionRuntime(manager, controller)
    events = AutonomousEventBus()
    store = MissionStore(tmp_path / "missions.json")
    async def runner(_): return MissionStatus.COMPLETED
    operator = AutonomousOperator(store, PerceptionService(controller, actions.world_state, events), events, runner)
    runtime = DashboardRuntime(store, events, operator, manager, actions)
    return runtime, DashboardService(runtime), RuntimeCommandGateway(runtime, TOKEN)


def test_dashboard_snapshot_uses_real_runtime_state_and_redacts_secrets(tmp_path):
    runtime, service, _ = dashboard(tmp_path)
    mission = Mission("real mission", "user", task_graph={"task": {"objective": "work", "status": "running"}},
                      current_state={"api_token": "never-show"})
    runtime.missions.save(mission)
    snapshot = service.snapshot()
    assert snapshot["overview"]["active_missions"] == 1
    assert snapshot["overview"]["active_tasks"] == 1
    assert snapshot["overview"]["active_agents"] == 0
    assert snapshot["missions"][0]["current_state"]["api_token"] == "[REDACTED]"


def test_dashboard_commands_require_authorization_and_emit_correlated_event(tmp_path):
    runtime, _, gateway = dashboard(tmp_path)
    mission = Mission("pause me", "user"); runtime.missions.save(mission)
    with pytest.raises(PermissionError):
        asyncio.run(gateway.execute("wrong-token-value", "pause_mission", {"mission_id": mission.mission_id}))
    result = asyncio.run(gateway.execute(TOKEN, "pause_mission", {"mission_id": mission.mission_id}))
    assert runtime.missions.load(mission.mission_id).status is MissionStatus.PAUSED
    event = runtime.events.replay()[0]
    assert result["correlation_id"] == event.correlation_id


def test_dashboard_http_api_auth_static_load_and_replay(tmp_path):
    runtime, service, gateway = dashboard(tmp_path)
    asyncio.run(runtime.events.publish(AutonomousEvent(EventType.MISSION_TRIGGERED, "mission")))
    server = DashboardServer(service, gateway); server.start()
    host, port = server.address; base = f"http://{host}:{port}"
    try:
        page = urlopen(base + "/", timeout=2)
        body = page.read()
        assert b"Command Center" in body
        assert b"Missions" in body and b"aria-live" in body
        assert page.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
        with pytest.raises(HTTPError) as denied:
            urlopen(base + "/api/system", timeout=2)
        assert denied.value.code == 401
        request = Request(base + "/api/system", headers={"Authorization": f"Bearer {TOKEN}"})
        payload = json.loads(urlopen(request, timeout=2).read())
        assert payload["events"][0]["mission_id"] == "mission"
        request = Request(base + "/api/events?since=1", headers={"Authorization": f"Bearer {TOKEN}"})
        assert json.loads(urlopen(request, timeout=2).read()) == []
    finally:
        server.close()


def test_dashboard_event_history_survives_gateway_restart(tmp_path):
    from app.autonomy.event_store import EventStore
    path = tmp_path / "events.db"
    store = EventStore(path); first = AutonomousEventBus(persistence=store)
    asyncio.run(first.publish(AutonomousEvent(EventType.TASK_COMPLETED, "mission", {"status": "completed"})))
    store.close()
    reopened = EventStore(path); restored = AutonomousEventBus(persistence=reopened)
    try:
        assert restored.replay()[0].mission_id == "mission"
        assert restored.replay()[0].sequence == 1
    finally:
        reopened.close()


def test_authorized_create_mission_uses_operator_and_validates_input(tmp_path):
    runtime, _, gateway = dashboard(tmp_path)
    result = asyncio.run(gateway.execute(TOKEN, "create_mission", {"goal": "Monitor project", "priority": 4}))
    mission = runtime.missions.load(runtime.events.replay()[-1].mission_id)
    assert result["accepted"] and mission.goal == "Monitor project" and mission.priority == 4
    with pytest.raises(ValueError):
        asyncio.run(gateway.execute(TOKEN, "create_mission", {"goal": ""}))


def test_analytics_use_real_denominators_and_report_unavailable_without_data(tmp_path):
    runtime, service, _ = dashboard(tmp_path)
    assert service.analytics()["mission_success_rate"] is None
    runtime.missions.save(Mission("done", "user", status=MissionStatus.COMPLETED,
        task_graph={"task": {"objective": "done", "status": "completed", "retries": 0}}))
    analytics = service.snapshot()["analytics"]
    assert analytics["mission_success_rate"] == 1.0
    assert analytics["task_success_rate"] == 1.0


def test_dashboard_approval_decision_flows_through_durable_runtime_authority(tmp_path):
    from app.autonomy.approvals import ApprovalStore, ApprovalSystem
    from app.autonomy.models import ComputerAction
    from app.safety.permissions import Permission

    async def scenario():
        runtime, service, _ = dashboard(tmp_path)
        approval_system = ApprovalSystem(ApprovalStore(tmp_path / "approvals.json"), runtime.agents, timeout_seconds=2)
        runtime = DashboardRuntime(runtime.missions, runtime.events, runtime.operator, runtime.agents,
                                   runtime.actions, approval_system=approval_system)
        gateway = RuntimeCommandGateway(runtime, TOKEN)
        action = ComputerAction("keyboard.write", {"text": "not persisted"},
                                runtime.agents.list_agents()[0].agent_id, "mission:task",
                                "send text", Permission.KEYBOARD_WRITE.value)
        waiter = asyncio.create_task(approval_system.request(action))
        await asyncio.sleep(.05)
        pending = DashboardService(runtime).snapshot()["approvals"]
        assert pending[0]["approval_id"] == action.action_id
        assert "not persisted" not in (tmp_path / "approvals.json").read_text()
        await gateway.execute(TOKEN, "approve", {"approval_id": action.action_id})
        assert await waiter is True
        assert DashboardService(runtime).snapshot()["approvals"] == []
    asyncio.run(scenario())


def test_dashboard_correlates_agents_actions_and_events_to_authoritative_mission(tmp_path):
    from app.autonomy.models import AuditRecord
    from datetime import datetime, timezone

    runtime, service, _ = dashboard(tmp_path)
    agent = runtime.agents.list_agents()[0]
    mission = Mission("trace work", "user", task_graph={
        "trace-task": {"objective": "trace", "status": "running"}})
    runtime.missions.save(mission)
    agent.current_task_id = "trace-task"
    runtime.actions.audit.append(AuditRecord(
        datetime.now(timezone.utc), agent.agent_id, None, "trace-task", "action",
        "filesystem.read", "filesystem.read", {}, "ok", None, 1,
        "auto_approve", "not_required"))
    asyncio.run(runtime.events.publish(AutonomousEvent(
        EventType.ACTION_RECORDED, detail={"task_id": "trace-task", "agent_id": agent.agent_id})))

    snapshot = service.snapshot()
    assert snapshot["agents"][0]["mission_id"] == mission.mission_id
    assert snapshot["actions"][0]["mission_id"] == mission.mission_id
    assert snapshot["events"][0]["mission_id"] == mission.mission_id
