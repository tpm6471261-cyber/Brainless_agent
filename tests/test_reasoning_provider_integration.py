import asyncio

from app.autonomy.models import ActionProposal, ComputerState, DecisionContext
from app.autonomy.proposals import ReasoningContext
from app.autonomy.reasoning_provider import ChatbotReasoningProvider
from app.autonomy.world_model import WorldModel


class FakeChatbot:
    def __init__(self, response): self.response, self.prompts = response, []
    async def open(self): pass
    async def verify_page(self): pass
    async def start_conversation(self): pass
    async def send_prompt(self, prompt): self.prompts.append(prompt)
    async def wait_for_response(self, timeout): self.timeout = timeout
    async def extract_response(self): return self.response


def test_chatbot_reasoning_adapter_redacts_context_and_returns_only_proposal_data():
    response = ('{"proposal_id":"p","goal_id":"g","task_id":"t","proposal_type":"action",'
                '"intent":"write","candidate_actions":[{"action_type":"keyboard.write",'
                '"arguments":{"text":"ok"},"reason":"requested"}],"confidence":0.5}')
    chatbot = FakeChatbot(response)
    context = ReasoningContext(DecisionContext("agent", "t", "goal", {"api_token": "do-not-send"}),
                               frozenset({"keyboard.write"}), frozenset({"keyboard.write"}),
                               {"password": "hidden", "safe": "visible"})
    proposal = asyncio.run(ChatbotReasoningProvider(chatbot).propose(context))
    assert proposal.task_id == "t" and proposal.candidate_actions[0].action_type == "keyboard.write"
    prompt = chatbot.prompts[0]
    assert "do-not-send" not in prompt and "hidden" not in prompt and "[REDACTED]" in prompt


def test_world_model_exports_serializable_evidence_for_checkpoint_and_learning():
    model = WorldModel()
    model.state.capture(ComputerState(browser_url="before"))
    model.predict("click", {"browser_url": "after"})
    comparison = model.compare("click", model.state.capture(ComputerState(browser_url="after")))
    exported = model.export_state()
    assert not comparison.invalidated
    assert exported["predictions"] == []
    assert exported["causal_evidence"][0]["supporting"] == 1


def test_agent_manager_assigns_and_rebinds_stable_task_ids():
    from app.agents.manager import AgentManager
    manager = AgentManager()
    root = manager.create_root("root", "root", "goal", set())
    child = manager.create_agent(root.agent_id, "child", "worker", "goal", task="first")
    first = child.current_task_id
    assert first and child.context["task_id"] == first
    manager.assign_task(root.agent_id, child.agent_id, "second", task_id="task-2")
    assert child.current_task_id == "task-2" and child.context["task_id"] == "task-2"


def test_orchestrator_uses_configured_reasoning_provider_only_through_validator():
    from app.agents.manager import AgentManager
    from app.autonomy.executor import ActionRuntime
    from app.autonomy.orchestrator import AutonomousRuntime
    from app.autonomy.proposals import ProposalType, ReasoningProposal
    from app.safety.permissions import Permission

    class Controller:
        def __init__(self): self.clicked = False
        async def observe(self): return ComputerState(browser_url="after" if self.clicked else "before")
        async def execute(self, action, arguments): self.clicked = action == "mouse.click"; return "clicked"

    class Provider:
        def __init__(self): self.done = False
        async def propose(self, context):
            if self.done: return None
            self.done = True
            return ReasoningProposal("proposal", "goal", context.decision.task_id, ProposalType.ACTION, "click", (
                ActionProposal(
                    "mouse.click", {"x": 1, "y": 2}, "requested", {"browser_url": "after"}),),
                required_permissions=frozenset({Permission.MOUSE_CLICK.value}), confidence=.9)

    async def scenario():
        manager = AgentManager()
        root = manager.create_root("root", "root", "goal", {Permission.SCREEN_READ.value, Permission.MOUSE_CLICK.value})
        actions = ActionRuntime(manager, Controller())
        result = await AutonomousRuntime(manager, actions, reasoning_provider=Provider()).execute(root.agent_id, "stable-task", "click button")
        assert result.actions == 1
    asyncio.run(scenario())
