import asyncio

from app.autonomy.events import AutonomousEvent, AutonomousEventBus, EventType
from app.autonomy.mission import Mission, MissionStatus, MissionStore
from app.autonomy.operator import AutonomousOperator, AutonomyMode
from app.autonomy.perception_service import PerceptionService
from app.autonomy.models import ComputerState
from app.autonomy.world_state import WorldStateManager

class Controller:
    def __init__(self): self.state = "before"; self.observations = 0
    async def observe(self): self.observations += 1; return ComputerState(active_window=self.state, browser_url=self.state)


def build(tmp_path, runner):
    events = AutonomousEventBus(); controller = Controller()
    return AutonomousOperator(MissionStore(tmp_path / "missions.json"),
        PerceptionService(controller, WorldStateManager(), events), events, runner), controller


def test_persistent_mission_observes_runs_verifies_and_restores_after_restart(tmp_path):
    async def runner(mission):
        mission.task_graph = {"report": {"status": "completed"}}
        mission.checkpoint["verified"] = True
        return MissionStatus.COMPLETED
    async def scenario():
        operator, controller = build(tmp_path, runner)
        mission = await operator.create(Mission("prepare report", "user", priority=3))
        done = await operator.run_once(mission.mission_id)
        assert done.status is MissionStatus.COMPLETED and done.progress["verification_status"]
        # A fresh supervisor loads durable state and does not replay terminal actions.
        restored, _ = build(tmp_path, runner)
        assert (await restored.resume_active()) == ()
        assert controller.observations == 1
    asyncio.run(scenario())


def test_takeover_pauses_actions_then_resume_reobserves_and_continues(tmp_path):
    calls = []
    async def runner(mission): calls.append(mission.mission_id); return MissionStatus.COMPLETED
    async def scenario():
        operator, controller = build(tmp_path, runner)
        mission = await operator.create(Mission("login then continue", "user"))
        await operator.process_event(AutonomousEvent(EventType.USER_TAKEOVER, mission.mission_id))
        paused = await operator.run_once(mission.mission_id)
        assert paused.status is MissionStatus.AWAITING_USER and not calls
        operator.takeover.resume()
        done = await operator.run_once(mission.mission_id)
        assert done.status is MissionStatus.COMPLETED and len(calls) == 1 and controller.observations == 2
    asyncio.run(scenario())


def test_event_bus_and_blockers_update_mission_without_reasoning_calls(tmp_path):
    async def runner(_): return MissionStatus.COMPLETED
    async def scenario():
        operator, _ = build(tmp_path, runner)
        mission = await operator.create(Mission("wait for resource", "user"))
        await operator.events.publish(AutonomousEvent(EventType.RESOURCE_CONFLICT, mission.mission_id))
        await operator.events.next(0)  # consume creation trigger
        event = await operator.events.next(0)
        updated = await operator.process_event(event)
        assert updated.status is MissionStatus.WAITING
    asyncio.run(scenario())


def test_explicitly_paused_mission_never_runs_or_observes_until_resumed(tmp_path):
    calls = []
    async def runner(mission):
        calls.append(mission.mission_id)
        return MissionStatus.COMPLETED
    async def scenario():
        operator, controller = build(tmp_path, runner)
        mission = await operator.create(Mission("pause safely", "user"))
        mission.status = MissionStatus.PAUSED
        operator.store.save(mission)
        paused = await operator.run_once(mission.mission_id)
        assert paused.status is MissionStatus.PAUSED
        assert calls == [] and controller.observations == 0
        paused.status = MissionStatus.WAITING
        operator.store.save(paused)
        done = await operator.run_once(mission.mission_id)
        assert done.status is MissionStatus.COMPLETED and len(calls) == 1
    asyncio.run(scenario())


def test_operator_dispatches_events_to_runtime_trigger_handlers(tmp_path):
    handled = []
    async def runner(_): return MissionStatus.COMPLETED
    async def handler(event): handled.append(event.type)
    async def scenario():
        operator, _ = build(tmp_path, runner)
        operator.event_handlers = (handler,)
        await operator.process_event(AutonomousEvent(EventType.FILE_CREATED))
        assert handled == [EventType.FILE_CREATED]
    asyncio.run(scenario())
