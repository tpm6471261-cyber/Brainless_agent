"""Run the authenticated Brainless Agent web command center and mission operator."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from app.autonomy.event_store import EventStore
from app.autonomy.events import AutonomousEventBus
from app.autonomy.mission import MissionStore
from app.autonomy.operator import AutonomousOperator
from app.autonomy.perception_service import PerceptionService
from app.autonomy.production_mission import RuntimeMissionComposer
from app.autonomy.reasoning_provider import ChatbotReasoningProvider
from app.autonomy.approvals import ApprovalStore, ApprovalSystem
from app.autonomy.mode_policy import ModePolicy
from app.autonomy.triggers import TriggerEngine, TriggerStore
from app.bootstrap import Application
from app.config.settings import load_settings
from app.dashboard import DashboardRuntime, DashboardServer, DashboardService, RuntimeCommandGateway
from app.dashboard.runtime_bridge import RuntimeEventBridge
from app.safety.permissions import Permission
from app.autonomy.operator import AutonomyMode
from app.autonomy.health import AgentHealthMonitor
from app.voice import AssemblyAISpeechProvider, VoiceConfig, VoiceControlPlane, VoiceMode, VoiceService
from app.voice.service import VoiceRuntimeRouter
from app.voice.store import VoiceMetadataStore
from app.perception import ComputerControllerSource, FilesystemPerceptionSource, MultimodalPerceptionEngine


async def _pump(bridge: RuntimeEventBridge, health: AgentHealthMonitor) -> None:
    while True:
        await bridge.pump_once()
        health.inspect()
        await asyncio.sleep(.25)


async def _tick_triggers(triggers: TriggerEngine) -> None:
    while True:
        await triggers.tick()
        await asyncio.sleep(1)


async def serve() -> None:
    token = os.environ.get("BRAINLESS_DASHBOARD_TOKEN", "")
    if len(token) < 16:
        raise SystemExit("Set BRAINLESS_DASHBOARD_TOKEN to at least 16 characters")
    root = Path(__file__).resolve().parent
    application = Application(root, load_settings())
    event_store = EventStore(root / "data/dashboard-events.db")
    events = AutonomousEventBus(persistence=event_store)
    missions = MissionStore(root / "data/missions.json")
    trigger_store = TriggerStore(root / "data/triggers.json")
    trigger_engine = TriggerEngine(trigger_store, events, policy=lambda trigger: (
        (mission := missions.load(trigger.mission_id)) is not None and
        mission.status.value not in {"completed", "failed", "cancelled"}))
    approvals = ApprovalSystem(ApprovalStore(root / "data/approvals.json"), application.agent_manager)
    application.autonomous_actions.approval_handler = approvals.request
    application.autonomous_actions.mode_policy = ModePolicy(AutonomyMode.SUPERVISED)
    execution_status = "not_configured"
    if application.providers.names:
        provider = application.providers.get(application.providers.names[0])
        application.autonomous.reasoning_provider = ChatbotReasoningProvider(provider)
        root_agent = application.agent_manager.create_root(
            "Root Operator", "orchestrator", "Supervise autonomous missions",
            {permission.value for permission in Permission})
        runner = RuntimeMissionComposer(application.autonomous, application.task_engine, root_agent.agent_id)
        execution_status = "healthy"
    else:
        async def runner(_):
            raise RuntimeError("No reasoning provider is configured")
    operator = AutonomousOperator(missions, PerceptionService(
        application.autonomous_actions.controller, application.autonomous_actions.world_state, events), events, runner,
        event_handlers=(trigger_engine.handle,))
    def create_voice(config: VoiceConfig) -> VoiceService:
        return VoiceService(config, AssemblyAISpeechProvider(config),
            VoiceRuntimeRouter(operator, missions, approvals), events,
            VoiceMetadataStore(root / "data/voice-sessions.json"))

    voice = VoiceControlPlane(create_voice)
    multimodal_perception = MultimodalPerceptionEngine((ComputerControllerSource(
        application.autonomous_actions.controller), FilesystemPerceptionSource(root)), events,
        world=application.autonomous_actions.world_state,
        capability_authorizer=lambda agent_id: set(application.agent_manager.get_agent(agent_id).permissions))
    multimodal_perception.on_human_required = lambda _: operator.takeover.begin()
    if os.environ.get("ASSEMBLYAI_API_KEY"):
        voice_config = VoiceConfig.from_env()
        voice.configure_config(voice_config)
        if voice_config.mode in {VoiceMode.ACTIVE, VoiceMode.SESSION}:
            await voice.start()
    runtime = DashboardRuntime(missions, events, operator, application.agent_manager,
        application.autonomous_actions, triggers=trigger_store, memory=application.memory,
        skills=application.skill_registry, provider_names=application.providers.names,
        mission_execution_status=execution_status, approval_system=approvals, voice=voice,
        perception=multimodal_perception)
    gateway = RuntimeCommandGateway(runtime, token)
    server = DashboardServer(DashboardService(runtime), gateway, port=8765,
        event_loop=asyncio.get_running_loop())
    bridge_task = asyncio.create_task(_pump(RuntimeEventBridge(
        application.agent_manager, application.autonomous_actions, events),
        AgentHealthMonitor(application.agent_manager, application.autonomous_actions.locks)))
    operator_task = asyncio.create_task(operator.run_background(stop=lambda: False))
    trigger_task = asyncio.create_task(_tick_triggers(trigger_engine))
    server.start()
    print("Command Center: http://127.0.0.1:8765")
    try:
        await asyncio.Event().wait()
    finally:
        operator_task.cancel(); bridge_task.cancel(); trigger_task.cancel()
        tasks = [operator_task, bridge_task, trigger_task]
        await voice.stop()
        await asyncio.gather(*tasks, return_exceptions=True)
        server.close(); event_store.close(); await application.close()


def main() -> None:
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
