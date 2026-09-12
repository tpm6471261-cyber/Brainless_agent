"""Application composition root shared by CLI and desktop UI."""
from __future__ import annotations

from pathlib import Path

from app.browser.browser_manager import BrowserManager
from app.agents.manager import AgentManager
from app.agents.runtime_tools import register_runtime_tools
from app.agents.tools import ToolRegistry
from app.computer.screenshot import ScreenshotRecorder
from app.config.settings import Settings
from app.memory.sqlite_memory import SQLiteMemory
from app.prompts.prompt_manager import PromptManager
from app.providers.registry import ProviderRegistry
from app.runtime.agent_runtime import AgentRuntime
from app.autonomy.controllers import PlaywrightComputerController
from app.autonomy.executor import ActionRuntime as AutonomousActionRuntime
from app.autonomy.orchestrator import AutonomousRuntime
from app.autonomy.task_engine import AutonomousTaskEngine
from app.safety.intervention import UserInterventionGate
from app.learning import ExperienceMemory, LearningCoordinator, SkillRegistry, AgentPerformanceMemory
from app.event_system import create_event_platform


class Application:
    def __init__(self, root: Path, settings: Settings, intervention: UserInterventionGate | None = None) -> None:
        self.memory = SQLiteMemory(root / "data/memory.db")
        self.browser = BrowserManager(settings.browser, root)
        tools = ToolRegistry()
        register_runtime_tools(tools, self.browser, root, screenshots=ScreenshotRecorder(root / "screenshots"))
        self.agent_manager = AgentManager(tools, audit_store=self.memory)
        # Desktop events/actions are composed independently from reasoning. Detectors remain
        # idle until a caller starts polling, and sensitive observation defaults to off.
        self.event_platform = create_event_platform()
        self.autonomous_actions = AutonomousActionRuntime(
            self.agent_manager, PlaywrightComputerController(self.browser), audit_store=self.memory)
        self.autonomous = AutonomousRuntime(self.agent_manager, self.autonomous_actions)
        # Learning stores structured runtime outcomes separately from conversational memory.
        self.experience_memory = ExperienceMemory(root / "data/experience.db")
        self.skill_registry = SkillRegistry(root / "data/skills.db")
        self.learning = LearningCoordinator(self.experience_memory, self.skill_registry)
        self.agent_performance = AgentPerformanceMemory(root / "data/agent_performance.db")
        # The normal autonomous entry point shares the controlled learning coordinator.
        self.task_engine = AutonomousTaskEngine(self.autonomous, self.autonomous_actions,
                                                journal=self.memory, learning=self.learning, performance=self.agent_performance)
        self.providers = ProviderRegistry.from_settings(self.browser, settings.providers)
        self.runtime = AgentRuntime(
            self.browser, self.providers, PromptManager(root / "prompts"), self.memory,
            settings.agent.max_retries, settings.agent.max_actions, settings.agent.max_task_minutes,
            screenshots=ScreenshotRecorder(root / "screenshots"),
            intervention=intervention,
        )

    async def close(self) -> None:
        self.event_platform.emergency_stop()
        self.event_platform.manager.stop()
        self.experience_memory.close()
        self.skill_registry.close()
        self.agent_performance.close()
        self.memory.close()
        await self.browser.close()
