import asyncio

from app.agents.manager import AgentManager
from app.autonomy.controllers import FilesystemComputerController
from app.autonomy.events import AutonomousEventBus
from app.autonomy.executor import ActionRuntime
from app.autonomy.mission import Mission, MissionStatus, MissionStore
from app.autonomy.models import ActionProposal
from app.autonomy.operator import AutonomousOperator
from app.autonomy.orchestrator import AutonomousRuntime
from app.autonomy.perception_service import PerceptionService
from app.autonomy.task_engine import AutonomousTaskEngine
from app.autonomy.task_graph import GraphTask, TaskGraph
from app.autonomy.task_runner import TaskEngineMissionRunner
from app.dashboard.runtime_bridge import RuntimeEventBridge
from app.dashboard.service import DashboardRuntime, DashboardService
from app.safety.permissions import Permission


def test_complete_verified_mission_is_visible_in_dashboard(tmp_path):
    class WriteOnce:
        def __init__(self): self.done = False
        async def next_action(self, _):
            if self.done: return None
            self.done = True
            return ActionProposal("filesystem.write", {"path": "report.txt", "content": "verified"}, "create report")

    class FileExists:
        async def verify(self, _):
            return ((tmp_path / "report.txt").read_text() == "verified", "report was not verified")

    async def scenario():
        manager = AgentManager()
        root = manager.create_root("operator", "root", "mission", {
            Permission.SCREEN_READ.value, Permission.FILESYSTEM_WRITE.value})
        controller = FilesystemComputerController(tmp_path)
        actions = ActionRuntime(manager, controller)
        autonomous = AutonomousRuntime(manager, actions)
        engine = AutonomousTaskEngine(autonomous, actions)
        graph = TaskGraph(); graph.add(GraphTask("write", "write report",
            capabilities=frozenset({"computer.observe", "filesystem.write"}),
            permissions=frozenset({Permission.FILESYSTEM_WRITE.value}),
            resources=frozenset({"filesystem"}), tool="filesystem.write"))
        runner = TaskEngineMissionRunner(engine, root.agent_id, lambda _: graph, lambda _: WriteOnce(), lambda _: (FileExists(),))
        events = AutonomousEventBus(); store = MissionStore(tmp_path / "missions.json")
        operator = AutonomousOperator(store, PerceptionService(controller, actions.world_state, events), events, runner)
        mission = await operator.create(Mission("Create a verified report", "user"))
        completed = await operator.run_once(mission.mission_id)
        await RuntimeEventBridge(manager, actions, events).pump_once()
        dashboard = DashboardService(DashboardRuntime(store, events, operator, manager, actions)).snapshot()
        assert completed.status is MissionStatus.COMPLETED
        assert dashboard["overview"]["completed_tasks"] == 1
        assert dashboard["missions"][0]["status"] == "completed"
        assert dashboard["actions"][0]["tool"] == "filesystem.write"
        assert any(event["event_type"] == "action_recorded" for event in dashboard["events"])
    asyncio.run(scenario())
