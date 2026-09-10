"""Root decision flow: analyse requirements, reuse or create, then supervise."""
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from app.agents.manager import AgentManager
from app.agents.models import Agent
from app.autonomy.executor import ActionRuntime, DecisionProvider
from app.autonomy.factory import AgentFactory
from app.autonomy.reasoning_provider import ReasoningDecisionProvider
from app.autonomy.models import AgentSpec, TaskRequirements
from app.autonomy.registry import AgentRegistry
from app.safety.permissions import Permission


@dataclass(frozen=True, slots=True)
class AutonomousResult:
    agent_id: str
    created: bool
    actions: int
    result: str


class CapabilityAnalyzer:
    """Conservative task analyser; replaceable by a model-backed planner later."""
    def analyze(self, task: str) -> TaskRequirements:
        lower = task.lower()
        capabilities: set[str] = {"computer.observe"}
        permissions: set[str] = {Permission.SCREEN_READ.value}
        tools: set[str] = set()
        role = "ComputerAgent"
        if any(word in lower for word in ("browser", "website", "web", "navigate", "url")):
            capabilities.add("browser.navigation"); permissions.add(Permission.BROWSER_NAVIGATE.value); tools.add("browser.navigate"); role = "BrowserAgent"
        if any(word in lower for word in ("document", "text editor", "write")):
            capabilities.add("keyboard.input"); permissions.add(Permission.KEYBOARD_WRITE.value); tools.add("keyboard.write")
        if any(word in lower for word in ("document", "save", "file")):
            capabilities.add("filesystem.write"); permissions.add(Permission.FILESYSTEM_WRITE.value); tools.add("filesystem.write")
            role = "DocumentAgent"
        if any(word in lower for word in ("click", "button", "mouse")):
            capabilities.add("mouse.control"); permissions.add(Permission.MOUSE_CLICK.value); tools.add("mouse.click")
        return TaskRequirements(frozenset(capabilities), frozenset(permissions), frozenset(tools), role)


class AutonomousRuntime:
    def __init__(self, manager: AgentManager, actions: ActionRuntime,
                 registry: AgentRegistry | None = None, analyzer: CapabilityAnalyzer | None = None,
                 reasoning_provider=None) -> None:
        self.manager, self.actions = manager, actions
        self.registry, self.analyzer = registry or AgentRegistry(), analyzer or CapabilityAnalyzer()
        self.reasoning_provider = reasoning_provider
        self.factory = AgentFactory(manager)

    async def execute(self, root_agent_id: str, task_id: str, task: str, decider: DecisionProvider | None = None,
                      requirements: TaskRequirements | None = None) -> AutonomousResult:
        # Graph execution supplies validated requirements; ad-hoc execution is analysed.
        if decider is None:
            if self.reasoning_provider is None:
                raise RuntimeError("A DecisionProvider or configured ReasoningProvider is required")
            decider = ReasoningDecisionProvider(self.reasoning_provider, self.actions.proposal_validator, self.manager)
        requirements = requirements or self.analyzer.analyze(task)
        agent = self.registry.find(requirements)
        created = agent is None
        if agent is None:
            agent = self.factory.create(root_agent_id, AgentSpec(
                name=requirements.role, role=requirements.role, objective=f"Execute {task}", task=task,
                required_capabilities=requirements.capabilities, tools=requirements.tools, task_id=task_id,
                constraints={"least_privilege": True},
            ))
            self.registry.register(agent, requirements.capabilities)
        else:
            self.manager.assign_task(root_agent_id, agent.agent_id, task, task_id=task_id)

        async def work(child: Agent, _: AgentManager) -> str:
            results = await self.actions.run_loop(child.agent_id, task_id, task, decider)
            if not results or not results[-1].success:
                raise RuntimeError("Autonomous task did not produce a verified action")
            successful = sum(result.success and result.verified for result in results)
            recovered = len(results) - successful
            suffix = f" after {recovered} recovered failure(s)" if recovered else ""
            return f"Completed {successful} verified action(s){suffix}"

        started = monotonic()
        try:
            outcome = await self.manager.start_agent(root_agent_id, agent.agent_id, work)
        except Exception:
            self.registry.record_result(agent.agent_id, success=False, verified=False,
                                        duration_ms=(monotonic() - started) * 1000)
            raise
        self.registry.record_result(agent.agent_id, success=True, verified=True,
                                    duration_ms=(monotonic() - started) * 1000)
        return AutonomousResult(agent.agent_id, created, len(agent.execution_history), outcome)
