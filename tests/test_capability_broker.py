import asyncio

from app.agents.manager import AgentManager
from app.agents.tools import RiskLevel, ToolRegistry, ToolSpec
from app.autonomy.capability_broker import CapabilityBroker, CapabilityStatus
from app.autonomy.mission import Mission, MissionStatus
from app.autonomy.orchestrator import CapabilityAnalyzer
from app.autonomy.registry import AgentRegistry
from app.dashboard.service import DashboardRuntime, DashboardService, RuntimeCommandGateway
from tests.test_dashboard import TOKEN, dashboard


def broker(manager=None, registry=None):
    manager = manager or AgentManager()
    return CapabilityBroker(manager, registry or AgentRegistry(), CapabilityAnalyzer())


def test_video_goal_detects_real_local_gap_and_builds_safe_discovery_mission():
    assessment = broker().assess("Edit my video and add subtitles")
    assert assessment.status is CapabilityStatus.DISCOVERY_REQUIRED
    assert assessment.domain == "video_editing"
    assert assessment.missing_tools == ("video.edit",)
    assert "free open-source local video editing" in assessment.discovery_query

    original = Mission("Edit my video", "user")
    discovery = broker().discovery_mission(original, assessment)
    assert "Use the browser to research" in discovery.goal
    assert {"no_purchase", "no_install", "no_signup", "no_external_execution"} <= set(discovery.constraints)
    assert discovery.current_state["capability_discovery_for"] == original.mission_id


def test_broker_prefers_compatible_local_agent_before_discovery():
    tools = ToolRegistry()
    tools.register(ToolSpec("video.edit", "Video editor", "Verified local edit", frozenset(),
                            RiskLevel.MEDIUM, lambda _: "ok"))
    manager = AgentManager(tools)
    root = manager.create_root("root", "root", "supervise", set())
    child = manager.create_agent(root.agent_id, "editor", "VideoEditingAgent", "edit",
                                 tools={"video.edit"})
    registry = AgentRegistry()
    registry.register(child, frozenset({"video.edit"}))

    assessment = broker(manager, registry).assess("Please edit video")
    assert assessment.status is CapabilityStatus.LOCAL_AGENT
    assert assessment.matching_agent_ids == (child.agent_id,)
    assert assessment.missing_tools == ()


def test_dashboard_pauses_unsupported_goal_and_starts_constrained_discovery(tmp_path):
    async def scenario():
        base, _, _ = dashboard(tmp_path)
        capability_broker = broker(base.agents, AgentRegistry())
        runtime = DashboardRuntime(base.missions, base.events, base.operator, base.agents,
                                   base.actions, capability_broker=capability_broker)
        result = await RuntimeCommandGateway(runtime, TOKEN).execute(
            TOKEN, "create_mission", {"goal": "Edit video and add subtitles"})
        assert result["capability_status"] == "discovery_required"
        missions = runtime.missions.all()
        original = next(item for item in missions if item.goal == "Edit video and add subtitles")
        discovery = next(item for item in missions if item.mission_id == result["discovery_mission_id"])
        assert original.status is MissionStatus.PAUSED
        assert discovery.status is MissionStatus.PLANNING
        assert "no_external_execution" in discovery.constraints
        snapshot = DashboardService(runtime).snapshot()
        assert snapshot["overview"]["capability_gaps"] == 1
        assert snapshot["capability_gaps"][0]["domain"] == "video_editing"

    asyncio.run(scenario())
