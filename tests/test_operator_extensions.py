import asyncio
from datetime import datetime, timedelta, timezone

from app.autonomy.events import AutonomousEvent, AutonomousEventBus, EventType
from app.autonomy.triggers import FilesystemWatcher, Trigger, TriggerEngine, TriggerKind, TriggerStore


def test_persisted_time_and_filesystem_triggers_are_deterministic(tmp_path):
    async def scenario():
        events = AutonomousEventBus(); store = TriggerStore(tmp_path / "triggers.json")
        trigger = Trigger("mission", TriggerKind.TIME, (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
        store.save(trigger)
        assert (await TriggerEngine(store, events).tick())[0].trigger_id == trigger.trigger_id
        assert (await events.next(0)).type is EventType.TIME_TRIGGERED
    asyncio.run(scenario())
    watcher = FilesystemWatcher(tmp_path); assert watcher.poll() == ()
    (tmp_path / "new.txt").write_text("new")
    assert EventType.FILE_CREATED in watcher.poll()


def test_health_monitor_releases_dead_agent_resources_without_escalation():
    from app.agents.manager import AgentManager
    from app.agents.models import AgentStatus
    from app.autonomy.health import AgentHealthMonitor
    from app.autonomy.resources import ResourceLockManager
    async def scenario():
        manager = AgentManager(); root = manager.create_root("root", "root", "goal", set())
        child = manager.create_agent(root.agent_id, "worker", "worker", "work", task="task")
        locks = ResourceLockManager()
        async with locks.acquire(child.agent_id, {"browser"}):
            child.status = AgentStatus.FAILED
            health = AgentHealthMonitor(manager, locks).inspect()
            assert not health[1].healthy and health[1].released_resources == ("browser",)
    asyncio.run(scenario())


def test_mode_policy_blocks_watch_and_requires_supervised_approval():
    from app.agents.tools import RiskLevel, ToolSpec
    from app.autonomy.mode_policy import ModePolicy
    from app.autonomy.operator import AutonomyMode
    high = ToolSpec("danger", "danger", "", frozenset(), RiskLevel.HIGH, lambda _: None)
    assert ModePolicy(AutonomyMode.WATCH).decision(high) == "deny"
    assert ModePolicy(AutonomyMode.SUPERVISED).decision(high) == "approval"


def test_task_engine_mission_runner_restores_graph_and_maps_verified_outcome():
    from app.autonomy.mission import Mission, MissionStatus
    from app.autonomy.task_engine import TaskResult, TaskOutcome
    from app.autonomy.task_graph import GraphTask, TaskGraph
    from app.autonomy.task_runner import TaskEngineMissionRunner

    class Engine:
        async def run_graph(self, root, task, graph, decider):
            assert root == "root" and graph.tasks["first"].status.value == "completed"
            graph.complete("second")
            return TaskResult(task.task_id, TaskOutcome.COMPLETED, "done", True, completed_tasks=("first", "second"))
    def graph_for(_):
        graph = TaskGraph(); graph.add(GraphTask("first", "first")); graph.add(GraphTask("second", "second", {"first"})); return graph
    runner = TaskEngineMissionRunner(Engine(), "root", graph_for, lambda _: None, lambda _: ())
    mission = Mission("goal", "user", checkpoint={"task_graph": {"first": {"status": "completed"}}})
    assert asyncio.run(runner(mission)) is MissionStatus.COMPLETED
    assert mission.checkpoint["verified"] and mission.task_graph["second"]["status"] == "completed"


def test_condition_and_prerequisite_mission_triggers_respect_runtime_policy(tmp_path):
    async def scenario():
        events = AutonomousEventBus(); store = TriggerStore(tmp_path / "triggers.json")
        condition = {"ready": False}
        blocked = Trigger("blocked", TriggerKind.CONDITION, "ready")
        prerequisite = Trigger("dependent", TriggerKind.MISSION, "source")
        store.save(blocked); store.save(prerequisite)
        engine = TriggerEngine(store, events, conditions={"ready": lambda: condition["ready"]})
        assert await engine.tick() == ()
        condition["ready"] = True
        assert (await engine.tick())[0].mission_id == "blocked"
        assert (await engine.handle(AutonomousEvent(EventType.TASK_COMPLETED, "source")))[0].mission_id == "dependent"
    asyncio.run(scenario())


def test_benchmark_harness_records_verified_local_report_workflow(tmp_path):
    from app.autonomy.benchmark import BenchmarkHarness
    async def report_scenario():
        source = tmp_path / "source.txt"; source.write_text("research")
        report = tmp_path / "report.pdf"; report.write_bytes(b"%PDF-1.4\nresearch")
        archive = tmp_path / "archive"; archive.mkdir(); source.replace(archive / source.name)
        verified = report.read_bytes().startswith(b"%PDF") and (archive / "source.txt").is_file()
        return verified, verified, {"steps": 3, "agents": 1}
    result = asyncio.run(BenchmarkHarness().run("report_pdf_organize", report_scenario))
    assert result.success and result.verified and result.steps == 3


def test_interruption_and_presence_detection_keep_user_data_out_of_runtime():
    from app.autonomy.monitoring import InterruptionKind, InterruptionManager, UserPresenceDetector
    from app.autonomy.models import ComputerState
    interruption = InterruptionManager().classify(ComputerState(visible_ui=("Please sign in",)))
    assert interruption.kind is InterruptionKind.LOGIN and interruption.requires_user
    detector = UserPresenceDetector(lambda: True)
    assert detector.present() and detector.last_seen is not None


def test_supervised_runtime_waits_for_independent_approval_before_execution(tmp_path):
    from app.agents.manager import AgentManager
    from app.autonomy.approvals import ApprovalStatus, ApprovalStore, ApprovalSystem
    from app.autonomy.controllers import FilesystemComputerController
    from app.autonomy.executor import ActionRuntime
    from app.autonomy.mode_policy import ModePolicy
    from app.autonomy.models import ActionProposal
    from app.autonomy.operator import AutonomyMode
    from app.safety.permissions import Permission

    async def scenario():
        manager = AgentManager()
        root = manager.create_root("root", "root", "goal", {Permission.FILESYSTEM_WRITE.value})
        approvals = ApprovalSystem(ApprovalStore(tmp_path / "approvals.json"), manager, timeout_seconds=2)
        runtime = ActionRuntime(manager, FilesystemComputerController(tmp_path),
            approval_handler=approvals.request, mode_policy=ModePolicy(AutonomyMode.SUPERVISED))
        child = manager.create_agent(root.agent_id, "writer", "writer", "write", task="write",
            permissions={Permission.FILESYSTEM_WRITE.value}, tools={"filesystem.write"}, task_id="task")
        async def work(agent, _):
            pending = asyncio.create_task(runtime.perform_proposal(agent.agent_id, "task",
                ActionProposal("filesystem.write", {"path": "approved.txt", "content": "yes"}, "write approved file")))
            await asyncio.sleep(.05)
            request = approvals.store.all()[0]
            assert not (tmp_path / "approved.txt").exists()
            approvals.decide(request.approval_id, ApprovalStatus.APPROVED, "human")
            result = await pending
            assert result.success and (tmp_path / "approved.txt").read_text() == "yes"
            return "done"
        await manager.start_agent(root.agent_id, child.agent_id, work)
    asyncio.run(scenario())


def test_autonomy_governor_enforces_mission_authority_and_budgets(tmp_path):
    from app.agents.manager import AgentManager
    from app.autonomy.controllers import FilesystemComputerController
    from app.autonomy.executor import ActionRuntime
    from app.autonomy.governor import MissionContract
    from app.autonomy.models import ActionProposal
    from app.safety.permissions import Permission

    async def scenario():
        manager = AgentManager()
        root = manager.create_root("root", "root", "goal", {Permission.FILESYSTEM_WRITE.value})
        runtime = ActionRuntime(manager, FilesystemComputerController(tmp_path))
        agent = manager.create_agent(root.agent_id, "writer", "writer", "write", task="write",
            permissions={Permission.FILESYSTEM_WRITE.value}, tools={"filesystem.write"}, task_id="m:task")
        runtime.governor.register(MissionContract("m", allowed_tools=frozenset({"filesystem.write"}),
            allowed_permissions=frozenset({Permission.FILESYSTEM_WRITE.value}), max_actions=1), {"m:task"})
        # High-risk contracted actions require independent approval.
        first = await runtime.perform_proposal(agent.agent_id, "m:task",
            ActionProposal("filesystem.write", {"path": "one", "content": "one"}, "write"))
        assert not first.success and "APPROVAL_REQUIRED" in first.error
        # The failed attempt consumes the explicit action/failure accounting budget.
        second = await runtime.perform_proposal(agent.agent_id, "m:task",
            ActionProposal("filesystem.write", {"path": "two", "content": "two"}, "write"))
        assert not second.success and "mission_budget_exhausted" in second.error
        assert not (tmp_path / "one").exists() and not (tmp_path / "two").exists()
    asyncio.run(scenario())


def test_runtime_deduplicates_same_action_identity(tmp_path):
    from app.agents.manager import AgentManager
    from app.autonomy.controllers import FilesystemComputerController
    from app.autonomy.executor import ActionRuntime
    from app.autonomy.models import ComputerAction
    from app.safety.permissions import Permission

    async def scenario():
        manager = AgentManager()
        root = manager.create_root("root", "root", "goal", {Permission.FILESYSTEM_WRITE.value})
        runtime = ActionRuntime(manager, FilesystemComputerController(tmp_path))
        agent = manager.create_agent(root.agent_id, "writer", "writer", "write", task="write",
            permissions={Permission.FILESYSTEM_WRITE.value}, tools={"filesystem.write"}, task_id="task")
        action = ComputerAction("filesystem.write", {"path": "once", "content": "value"},
            agent.agent_id, "task", "write once", Permission.FILESYSTEM_WRITE.value)
        first = await runtime.perform(action)
        second = await runtime.perform(action)
        assert first is second and len(runtime.audit) == 1
    asyncio.run(scenario())


def test_capability_lease_is_task_scoped_and_fail_closed_on_revoke(tmp_path):
    from app.agents.manager import AgentManager
    from app.autonomy.controllers import FilesystemComputerController
    from app.autonomy.executor import ActionRuntime
    from app.safety.permissions import Permission

    async def scenario():
        manager = AgentManager()
        root = manager.create_root("root", "root", "goal", {Permission.FILESYSTEM_READ.value})
        ActionRuntime(manager, FilesystemComputerController(tmp_path))
        child = manager.create_agent(root.agent_id, "reader", "reader", "read", task="read",
            task_id="mission:read", permissions={Permission.FILESYSTEM_READ.value}, tools={"filesystem.read"})
        manager.revoke_permission(root.agent_id, child.agent_id, Permission.FILESYSTEM_READ.value)
        lease = manager.lease_permission(root.agent_id, child.agent_id, Permission.FILESYSTEM_READ.value,
                                         "mission:read", seconds=60)
        assert manager.leases.permits(child.agent_id, Permission.FILESYSTEM_READ.value, "mission:read")
        manager.leases.revoke(lease.lease_id)
        assert not manager.leases.permits(child.agent_id, Permission.FILESYSTEM_READ.value, "mission:read")
    asyncio.run(scenario())


def test_persisted_event_details_are_redacted_before_storage(tmp_path):
    from app.autonomy.event_store import EventStore
    async def scenario():
        store = EventStore(tmp_path / "events.db")
        events = AutonomousEventBus(persistence=store)
        await events.publish(AutonomousEvent(EventType.USER_MESSAGE,
            detail={"message": "password is hunter2"}))
        assert events.replay()[0].detail["message"] == "[REDACTED]"
        store.close()
        assert "hunter2" not in (tmp_path / "events.db").read_bytes().decode(errors="ignore")
    asyncio.run(scenario())
