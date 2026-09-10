import asyncio

from app.agents.manager import AgentManager
from app.autonomy.controllers import FilesystemComputerController
from app.autonomy.events import AutonomousEventBus, EventType
from app.autonomy.executor import ActionRuntime
from app.autonomy.mission import Mission, MissionStatus, MissionStore
from app.autonomy.operator import AutonomousOperator
from app.autonomy.perception_service import PerceptionService
from app.dashboard.service import DashboardRuntime, DashboardService
from app.voice.config import VoiceConfig
from app.voice.intent import VoiceIntentEngine, VoiceIntentType
from app.voice.models import VoiceTurn
from app.voice.service import VoiceRuntimeRouter, VoiceService
from app.voice.store import VoiceMetadataStore


class FakeStreamingTransport:
    def __init__(self, failures=0):
        self.failures, self.connects, self.connected = failures, 0, False
        self.on_turn = None

    async def connect(self, on_turn, on_error):
        self.connects += 1
        if self.connects <= self.failures: raise ConnectionError("network")
        self.connected, self.on_turn = True, on_turn
        return "assembly-session"

    async def stream_microphone(self): return None
    async def disconnect(self): self.connected = False
    def health_check(self): return self.connected


def runtime(tmp_path, *, confidence=.75, store_transcripts=False, failures=0):
    manager = AgentManager(); manager.create_root("Operator", "root", "supervise", set())
    controller = FilesystemComputerController(tmp_path); actions = ActionRuntime(manager, controller)
    events = AutonomousEventBus(); missions = MissionStore(tmp_path / "missions.json")
    async def runner(_): return MissionStatus.COMPLETED
    operator = AutonomousOperator(missions, PerceptionService(controller, actions.world_state, events), events, runner)
    config = VoiceConfig("key", min_confidence=confidence, store_transcripts=store_transcripts,
                         reconnect_limit=3)
    transport = FakeStreamingTransport(failures)
    service = VoiceService(config, transport, VoiceRuntimeRouter(operator, missions), events,
                           VoiceMetadataStore(tmp_path / "voice.json"))
    return service, transport, missions, events, manager, actions, operator


def test_partial_turn_updates_ui_but_never_creates_mission(tmp_path):
    async def scenario():
        service, _, missions, events, *_ = runtime(tmp_path)
        await service.start()
        await service.process_turn(VoiceTurn("partial", "Open Chrome", .99, False))
        assert service.snapshot()["current_transcript"] == "Open Chrome"
        assert missions.all() == () and service.history == []
        assert events.replay()[-1].type is EventType.VOICE_PARTIAL
        assert "transcript" not in events.replay()[-1].detail
    asyncio.run(scenario())


def test_final_turn_creates_one_runtime_mission_and_dashboard_trace(tmp_path):
    async def scenario():
        service, _, missions, events, manager, actions, operator = runtime(tmp_path)
        await service.start()
        turn = VoiceTurn("final", "Open Chrome and search for AI news", .98, True)
        await service.process_turn(turn); await service.process_turn(turn)
        assert len(missions.all()) == 1 and missions.all()[0].owner == "voice"
        assert len(service.history) == 1
        dashboard = DashboardService(DashboardRuntime(missions, events, operator, manager, actions, voice=service)).snapshot()
        assert dashboard["voice"]["history"][0]["mission_id"] == missions.all()[0].mission_id
        assert events.replay()[-1].type is EventType.VOICE_COMMAND
    asyncio.run(scenario())


def test_low_confidence_and_sensitive_turns_do_not_execute_without_confirmation(tmp_path):
    async def scenario():
        service, _, missions, *_ = runtime(tmp_path)
        await service.start()
        await service.process_turn(VoiceTurn("low", "Open the drone", .4, True))
        await service.process_turn(VoiceTurn("delete", "Delete everything", .99, True))
        assert missions.all() == () and service.history[-1]["status"] == "waiting"
        await service.process_turn(VoiceTurn("confirm", "Yes", .99, True))
        assert len(missions.all()) == 1
    asyncio.run(scenario())


def test_connection_retries_cleanup_and_minimal_persistence(tmp_path):
    async def scenario():
        service, transport, *_ = runtime(tmp_path, failures=2)
        await service.start(); assert transport.connects == 3 and service.health_check()
        await service.process_turn(VoiceTurn("secret", "my password is hidden", .99, True))
        await service.stop(); assert not transport.connected
        stored = (tmp_path / "voice.json").read_text()
        assert "password" not in stored and "hidden" not in stored
    asyncio.run(scenario())


def test_interrupt_intents_have_deterministic_priority():
    engine = VoiceIntentEngine()
    assert engine.parse("Stop everything", 1).type is VoiceIntentType.EMERGENCY_STOP
    assert engine.parse("Pause", 1).type is VoiceIntentType.PAUSE
    assert engine.parse("What's running?", 1).type is VoiceIntentType.QUERY_STATUS


def test_voice_approval_fails_closed_without_independent_authorizer(tmp_path):
    async def scenario():
        service, *_ = runtime(tmp_path)
        result = await service.router.route(VoiceIntentEngine().parse("Approve", 1))
        assert result["status"] == "waiting"
        assert "authenticated dashboard" in result["result"]
    asyncio.run(scenario())


def test_voice_control_plane_reconnects_a_paused_session(tmp_path):
    from app.voice.controller import VoiceControlPlane
    async def scenario():
        service, transport, *_ = runtime(tmp_path)
        control = VoiceControlPlane(lambda _: service)
        control.configure("assembly-key-long-enough")
        await control.start()
        assert transport.connects == 1
        await service.pause()
        assert not control.health_check()
        await control.start()
        assert transport.connects == 2 and control.health_check()
        await control.stop()
    asyncio.run(scenario())


def test_voice_resume_transitions_paused_mission_and_emits_wakeup(tmp_path):
    async def scenario():
        service, _, missions, events, *_ = runtime(tmp_path)
        mission = Mission("continue safely", "voice", status=MissionStatus.PAUSED)
        missions.save(mission)
        result = await service.router.route(VoiceIntentEngine().parse("Resume", 1))
        assert result["status"] == "completed"
        assert missions.load(mission.mission_id).status is MissionStatus.WAITING
        assert events.replay()[-1].type is EventType.MISSION_TRIGGERED
    asyncio.run(scenario())
