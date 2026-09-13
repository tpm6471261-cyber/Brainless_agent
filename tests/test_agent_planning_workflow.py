import asyncio
import json
from types import SimpleNamespace

from app.agents.manager import AgentManager
from app.agents.planning import AgentPlanningWorkflow
from app.agents.tools import RiskLevel, ToolRegistry, ToolSpec


class FakeRegistry:
    def __init__(self):
        self.items = {}
        self.capabilities = {}

    def register(self, agent, capabilities):
        self.items[agent.agent_id] = agent
        self.capabilities[agent.agent_id] = capabilities

    def agents(self): return tuple(self.items.values())
    def capabilities_for(self, agent_id): return self.capabilities[agent_id]
    def available(self, agent_id): return self.items[agent_id].status.value in {"ready", "completed"}

    def find(self, requirements):
        return next((agent for agent in self.items.values()
                     if requirements.capabilities.issubset(self.capabilities[agent.agent_id])
                     and requirements.permissions.issubset(agent.permissions)
                     and requirements.tools.issubset(agent.available_tools)), None)


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def prepare_conversation(self, prompt): self.prompts.append(prompt)
    async def open(self): pass
    async def verify_page(self): pass
    async def start_conversation(self): pass
    async def send_prompt(self, _): pass
    async def wait_for_response(self): pass
    def remember_conversation(self): pass
    async def extract_response(self): return self.responses.pop(0)


def setup_runtime():
    tools = ToolRegistry()
    tools.register(ToolSpec("browser.navigate", "Navigate", "Navigate browser",
                            frozenset({"browser.navigate"}), RiskLevel.MEDIUM, lambda _: None))
    manager = AgentManager(tools)
    root = manager.create_root("Root", "operator", "Delegate", {"screen.read", "browser.navigate"})
    requirements = SimpleNamespace(capabilities=frozenset({"computer.observe", "browser.navigation"}),
                                   permissions=frozenset({"screen.read", "browser.navigate"}),
                                   tools=frozenset({"browser.navigate"}), role="BrowserAgent")
    return manager, root, FakeRegistry(), requirements


def definition(task):
    return {"name": "Web worker", "role": "BrowserAgent", "objective": task, "task": task,
            "permissions": ["browser.navigate", "screen.read"], "tools": ["browser.navigate"],
            "subscriptions": [], "context": {}, "resource_limits": {}, "allowed_applications": [],
            "allowed_directories": [], "risk_policy": "medium"}


def selection(requirements, decision, agent_id=None):
    return {"decision": decision, "agent_id": agent_id, "task": "Visit website",
            "required_capabilities": sorted(requirements.capabilities),
            "required_permissions": sorted(requirements.permissions),
            "required_tools": sorted(requirements.tools)}


def test_prompt1_reuses_an_authoritatively_eligible_agent(tmp_path):
    async def scenario():
        manager, root, registry, requirements = setup_runtime()
        existing = manager.create_agent(root.agent_id, "Existing", "BrowserAgent", "Browse",
                                        permissions=set(requirements.permissions),
                                        tools=set(requirements.tools))
        registry.register(existing, requirements.capabilities)
        provider = FakeProvider([json.dumps(selection(requirements, "reuse", existing.agent_id))])
        workflow = AgentPlanningWorkflow.__new__(AgentPlanningWorkflow)
        workflow.provider, workflow.manager, workflow.registry, workflow.root = provider, manager, registry, tmp_path
        workflow._provider_lock = asyncio.Lock()
        workflow.prompt1, workflow.prompt2 = "PROMPT1", "PROMPT2"
        agent, created = await workflow.select_or_create(root.agent_id, "task-1", "Visit website", requirements)
        assert agent is existing and not created
        assert agent.current_task_id == "task-1"
        assert len(provider.prompts) == 1
    asyncio.run(scenario())


def test_prompt2_creates_and_runs_only_a_validated_definition_artifact(tmp_path):
    async def scenario():
        manager, root, registry, requirements = setup_runtime()
        provider = FakeProvider([
            json.dumps(selection(requirements, "create")),
            json.dumps({"agent_definition": definition("Visit website"),
                        "python_code": "import os; os.system('must-not-run')"}),
        ])
        workflow = AgentPlanningWorkflow.__new__(AgentPlanningWorkflow)
        workflow.provider, workflow.manager, workflow.registry, workflow.root = provider, manager, registry, tmp_path
        workflow._provider_lock = asyncio.Lock()
        workflow.prompt1, workflow.prompt2 = "PROMPT1", "PROMPT2"
        agent, created = await workflow.select_or_create(root.agent_id, "task-2", "Visit website", requirements)
        artifact = (tmp_path / "data/generated-agents/task-2.py").read_text(encoding="utf-8")
        assert created and agent.permissions == set(requirements.permissions)
        assert agent.available_tools == set(requirements.tools)
        assert agent.current_task_id == "task-2" and registry.available(agent.agent_id)
        assert "os.system" not in artifact and "must-not-run" not in artifact
        assert len(provider.prompts) == 2
    asyncio.run(scenario())
