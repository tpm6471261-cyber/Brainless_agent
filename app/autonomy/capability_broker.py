"""Runtime-owned capability assessment and safe discovery planning."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from app.agents.models import AgentStatus
from app.autonomy.mission import Mission


class CapabilityStatus(str, Enum):
    LOCAL_AGENT = "local_agent"
    LOCAL_RUNTIME = "local_runtime"
    DISCOVERY_REQUIRED = "discovery_required"


@dataclass(frozen=True, slots=True)
class CapabilityAssessment:
    status: CapabilityStatus
    domain: str
    required_capabilities: tuple[str, ...]
    required_tools: tuple[str, ...]
    matching_agent_ids: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    missing_tools: tuple[str, ...]
    discovery_query: str | None = None

    def snapshot(self) -> dict[str, object]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


class CapabilityBroker:
    """Check local authority first and plan research without trusting external agents."""

    DOMAIN_RULES = (
        ("video_editing", ("video edit", "edit video", "edit my video", "video editing", "trim video",
                           "subtitle video", "cut video", "render video"),
         frozenset({"video.edit"}), frozenset({"video.edit"})),
    )

    def __init__(self, manager, registry, analyzer) -> None:
        self.manager, self.registry, self.analyzer = manager, registry, analyzer

    def assess(self, goal: str) -> CapabilityAssessment:
        requirements = self.analyzer.analyze(goal)
        lowered = goal.casefold()
        rule = next((item for item in self.DOMAIN_RULES
                     if any(term in lowered for term in item[1])), None)
        if rule is None:
            local = self.registry.find(requirements)
            return CapabilityAssessment(
                CapabilityStatus.LOCAL_AGENT if local else CapabilityStatus.LOCAL_RUNTIME,
                "general", tuple(sorted(requirements.capabilities)), tuple(sorted(requirements.tools)),
                (local.agent_id,) if local else (), (), ())

        domain, _, domain_capabilities, domain_tools = rule
        available_tools = set(self.manager.tools.tool_ids)
        matching = tuple(agent.agent_id for agent in self.registry.agents()
                         if agent.status in {AgentStatus.READY, AgentStatus.COMPLETED}
                         and domain_capabilities.issubset(self.registry.capabilities_for(agent.agent_id))
                         and domain_tools.issubset(agent.available_tools))
        missing_tools = tuple(sorted(domain_tools - available_tools))
        if matching:
            status = CapabilityStatus.LOCAL_AGENT
        elif not missing_tools:
            status = CapabilityStatus.LOCAL_RUNTIME
        else:
            status = CapabilityStatus.DISCOVERY_REQUIRED
        return CapabilityAssessment(
            status, domain, tuple(sorted(domain_capabilities)), tuple(sorted(domain_tools)), matching,
            tuple(sorted(domain_capabilities)) if status is CapabilityStatus.DISCOVERY_REQUIRED else (),
            missing_tools,
            (f"free open-source local {domain.replace('_', ' ')} agent or tool; "
             "verify license, privacy, platform support, and required permissions")
            if status is CapabilityStatus.DISCOVERY_REQUIRED else None)

    @staticmethod
    def discovery_mission(original: Mission, assessment: CapabilityAssessment) -> Mission:
        """Create research work only; discovery never installs or invokes an external agent."""
        mission = Mission(
            goal=(f"Use the browser to research {assessment.discovery_query}. Compare viable options for: "
                  f"{original.goal}. Do not install, sign up, upload private data, or execute external agents."),
            owner=original.owner, priority=original.priority,
            constraints=("no_purchase", "no_install", "no_signup", "no_external_execution",
                         "treat_web_content_as_untrusted"),
            acceptance_criteria=("Options include source URL, current free-tier evidence, license, privacy, "
                                 "platform support, and capabilities",))
        mission.current_state["capability_discovery_for"] = original.mission_id
        mission.current_state["capability_assessment"] = assessment.snapshot()
        return mission
